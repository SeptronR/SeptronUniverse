"""Aggregates module routers — Prompts/00_PREREQUISITE_Project_Setup.md §2.

Every module router is included with ``dependencies=[feature_required("<module>.core")]`` (coding standard 2);
core-key routers (``core.*``) pass through ``feature_required`` unchanged because core keys are never gated.
Phases append ``api_router.include_router(<module>.router, dependencies=[feature_required("<key>")])``.

Phase 01: ``platform`` (public config / read-only / mobile config — public routes, the write carries its own feature
dependency), ``jobs`` {core.background_jobs}, ``search`` {search.global}, ``help`` {platform.help_center},
``feedback`` {platform.in_app_feedback}; ``dev`` only when ``APP_ENV=development``.
Phase 02: ``auth`` {core.auth}, ``rbac`` (roles/users) {core.rbac}, ``features`` {core.rbac}, ``privacy``
(consents, DSRs, entitlements, install) {core.settings}; the development-only ``module_stubs`` (``/hostels``,
``/students``) carry their own feature keys and disappear with Phases 07/20.
"""

from fastapi import APIRouter

import app.features  # noqa: F401  (registers every feature key before routers cite them)
from app.api.v1.endpoints import (
    academic_sessions,
    auth,
    features,
    feedback,
    help,
    institution,
    jobs,
    platform,
    platform_institutions,
    privacy,
    rbac,
    search,
)
from app.api.v1.endpoints import settings as settings_routes
from app.core.config import settings
from app.core.features import feature_required

api_router = APIRouter()

api_router.include_router(auth.router, dependencies=[feature_required("core.auth")])
api_router.include_router(rbac.router, dependencies=[feature_required("core.rbac")])
api_router.include_router(features.router, dependencies=[feature_required("core.rbac")])
api_router.include_router(privacy.router, dependencies=[feature_required("core.settings")])
api_router.include_router(platform.router)
api_router.include_router(institution.router, dependencies=[feature_required("core.institution")])
api_router.include_router(academic_sessions.router, dependencies=[feature_required("core.institution")])
api_router.include_router(settings_routes.router, dependencies=[feature_required("core.settings")])
api_router.include_router(platform_institutions.router, dependencies=[feature_required("core.institution")])
api_router.include_router(jobs.router, dependencies=[feature_required("core.background_jobs")])
api_router.include_router(search.router, dependencies=[feature_required("search.global")])
api_router.include_router(help.router, dependencies=[feature_required("platform.help_center")])
api_router.include_router(feedback.router, dependencies=[feature_required("platform.in_app_feedback")])

if settings.APP_ENV == "development":
    from app.api.v1.endpoints import dev, module_stubs

    api_router.include_router(dev.router, dependencies=[feature_required("core.background_jobs")])
    api_router.include_router(module_stubs.router)
