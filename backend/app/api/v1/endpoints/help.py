"""Help-centre endpoints — Prompts/01 §01.8 (router included with ``feature_required("platform.help_center")``),
extended by Prompts/38 §38.8: ``?route=`` contextual lookup and the authoring routes ``/help/admin/*`` — platform
articles for the super admin (``platform:help``; support agents are refused), institution articles for the tenant's
``settings:manage`` (same slug overrides the platform article for that tenant only)."""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.endpoints.saas_deps import dual_db
from app.core.authz.dependencies import Principal, any_permission_required, permission_required
from app.db.session import get_db
from app.schemas.common import Envelope
from app.schemas.platform import HelpArticleResponse, HelpArticleSummary
from app.schemas.saas import HelpArticleAdminOut, HelpArticleIn, HelpImport
from app.services.help_service import HelpService
from app.services.saas.support_service import SupportService
from app.utils.response import ok

AUTHOR = any_permission_required(("settings", "manage"), ("platform", "help"))

router = APIRouter(prefix="/help", tags=["help"])


@router.get(
    "/articles",
    summary="Help articles (platform + institution), optionally by module",
    response_model=Envelope[list[HelpArticleSummary]],
)
async def list_articles(
    module: str | None = Query(None, max_length=60),
    q: str | None = Query(None, max_length=120),
    route: str | None = Query(None, max_length=200, description="client route → contextual article help:<route>"),
    principal: Principal = Depends(permission_required("dashboard", "view")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await HelpService(db, principal).list(module=module, q=q, route=route))


@router.get("/articles/{slug}", summary="Help article detail", response_model=Envelope[HelpArticleResponse])
async def get_article(
    slug: str,
    principal: Principal = Depends(permission_required("dashboard", "view")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await HelpService(db, principal).get(slug))


# ---- Phase 38 authoring ----------------------------------------------------------------------------------------------
@router.get(
    "/admin/articles",
    summary="Articles I author (platform or my institution)",
    response_model=Envelope[list[HelpArticleAdminOut]],
)
async def admin_articles(
    q: str | None = Query(None, max_length=120),
    module: str | None = Query(None, max_length=60),
    principal: Principal = Depends(AUTHOR),
    db: AsyncSession = Depends(dual_db),
) -> dict[str, Any]:
    return ok(await SupportService(db, principal).help_admin_list(q, module))


@router.post(
    "/admin/articles", status_code=201, summary="Create an article", response_model=Envelope[HelpArticleAdminOut]
)
async def admin_create(
    body: HelpArticleIn, request: Request, principal: Principal = Depends(AUTHOR), db: AsyncSession = Depends(dual_db)
) -> dict[str, Any]:
    return ok(await SupportService(db, principal, request).help_create(body), message="Article created")


@router.put("/admin/articles/{id}", summary="Update an article", response_model=Envelope[HelpArticleAdminOut])
async def admin_update(
    id: uuid.UUID,
    body: HelpArticleIn,
    request: Request,
    principal: Principal = Depends(AUTHOR),
    db: AsyncSession = Depends(dual_db),
) -> dict[str, Any]:
    return ok(await SupportService(db, principal, request).help_update(id, body), message="Article updated")


@router.delete("/admin/articles/{id}", status_code=204, summary="Delete an article")
async def admin_delete(
    id: uuid.UUID, request: Request, principal: Principal = Depends(AUTHOR), db: AsyncSession = Depends(dual_db)
) -> Response:
    await SupportService(db, principal, request).help_delete(id)
    return Response(status_code=204)


@router.get(
    "/admin/export",
    summary="Export platform articles (JSON, for docs/help versioning)",
    response_model=Envelope[list[dict[str, Any]]],
)
async def admin_export(principal: Principal = Depends(AUTHOR), db: AsyncSession = Depends(dual_db)) -> dict[str, Any]:
    return ok(await SupportService(db, principal).help_export())


@router.post(
    "/admin/import", summary="Import platform articles (upsert by slug)", response_model=Envelope[dict[str, int]]
)
async def admin_import(
    body: HelpImport, request: Request, principal: Principal = Depends(AUTHOR), db: AsyncSession = Depends(dual_db)
) -> dict[str, Any]:
    return ok(await SupportService(db, principal, request).help_import(body), message="Articles imported")
