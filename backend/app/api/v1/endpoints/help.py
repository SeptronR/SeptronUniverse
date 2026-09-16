"""Help-centre endpoints — Prompts/01 §01.8 (router included with ``feature_required("platform.help_center")``)."""

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, permission_required
from app.db.session import get_db
from app.schemas.common import Envelope
from app.schemas.platform import HelpArticleResponse, HelpArticleSummary
from app.services.help_service import HelpService
from app.utils.response import ok

router = APIRouter(prefix="/help", tags=["help"])


@router.get(
    "/articles",
    summary="Help articles (platform + institution), optionally by module",
    response_model=Envelope[list[HelpArticleSummary]],
)
async def list_articles(
    module: str | None = Query(None, max_length=60),
    q: str | None = Query(None, max_length=120),
    principal: Principal = Depends(permission_required("dashboard", "view")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await HelpService(db, principal).list(module=module, q=q))


@router.get("/articles/{slug}", summary="Help article detail", response_model=Envelope[HelpArticleResponse])
async def get_article(
    slug: str,
    principal: Principal = Depends(permission_required("dashboard", "view")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await HelpService(db, principal).get(slug))
