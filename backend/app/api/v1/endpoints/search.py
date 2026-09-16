"""Global search endpoint — Prompts/01 §01.8 (router included with ``feature_required("search.global")``)."""

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, permission_required
from app.db.session import get_db
from app.schemas.common import Envelope
from app.schemas.platform import SearchResponse
from app.services.search_service import SearchService
from app.utils.response import ok

router = APIRouter(prefix="/search", tags=["search"])


@router.get(
    "",
    summary="Global search (students, staff, courses, applicants) — visibility-aware",
    response_model=Envelope[SearchResponse],
)
async def search(
    q: str = Query(..., min_length=1, max_length=120),
    types: str | None = Query(None, description="comma-separated entity types: student,staff,course,applicant"),
    principal: Principal = Depends(permission_required("dashboard", "view")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    wanted = [t.strip() for t in types.split(",") if t.strip()] if types else None
    results, entity_types = await SearchService(db, principal).search(q, wanted)
    return ok(SearchResponse(q=q, results=results, entity_types=entity_types))
