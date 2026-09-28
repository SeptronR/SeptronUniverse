"""Public course catalogue — Prompts/05 §05.8 ``{public} {academics.public_catalog}`` (``PUBLIC_ROUTES``).

The tenant comes from ``?institution=<slug>`` / ``X-Institution-Slug`` / the custom host / ``X-Institution-Id``; the
route pins the RLS context to it (unauthenticated requests see nothing otherwise) and checks the feature itself —
``feature_required`` reads ``request.state.institution_id``, which a slug-only request does not carry.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError, ErrorCode
from app.core.features import is_enabled
from app.db.session import bind_tenant, get_db, set_tenant
from app.models.platform import Institution
from app.repositories.institution_repository import InstitutionRepository
from app.schemas.academics import PublicCatalogCourse, PublicCatalogProgram, PublicCatalogResponse
from app.schemas.common import Envelope
from app.services.catalog_service import CatalogService
from app.utils.response import ok

router = APIRouter(prefix="/public/catalog", tags=["public"])

FEATURE = "academics.public_catalog"


async def catalog_tenant(
    request: Request,
    institution: str | None = Query(default=None, max_length=60, description="institution slug"),
    db: AsyncSession = Depends(get_db),
) -> Institution:
    repo = InstitutionRepository(db)
    row: Institution | None = None
    slug = institution or getattr(request.state, "institution_slug", None)
    if slug:
        row = await repo.by_slug(slug)
    elif getattr(request.state, "institution_id", None):
        try:
            row = await repo.get(uuid.UUID(str(request.state.institution_id)))
        except ValueError:
            row = None
    if row is None or row.status != "active":
        raise APIError(404, ErrorCode.NOT_FOUND, "Institution not found")
    bind_tenant(db, row.id)
    await set_tenant(db, row.id)
    if not await is_enabled(row.id, FEATURE):
        raise APIError(403, ErrorCode.FEATURE_DISABLED, f"Feature '{FEATURE}' is not enabled", {"feature": FEATURE})
    return row


catalog_tenant.__feature_key__ = FEATURE  # type: ignore[attr-defined]  # read by check_authz_coverage / the matrix


@router.get("", summary="Public catalogue: programmes → public courses", response_model=Envelope[PublicCatalogResponse])
async def public_catalog(
    program: str | None = Query(default=None, max_length=30),
    level: str | None = Query(default=None, max_length=20),
    college: str | None = Query(default=None, max_length=20),
    inst: Institution = Depends(catalog_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CatalogService(db, inst).catalog(program, level, college))


@router.get(
    "/programs/{code}",
    summary="Public programme page (courses + syllabus)",
    response_model=Envelope[PublicCatalogProgram],
)
async def public_program(
    code: str,
    college: str | None = Query(default=None, max_length=20),
    inst: Institution = Depends(catalog_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CatalogService(db, inst).program_detail(code, college))


@router.get("/courses/{regulation}/{code}", summary="Public course page", response_model=Envelope[PublicCatalogCourse])
async def public_course(
    regulation: str,
    code: str,
    inst: Institution = Depends(catalog_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CatalogService(db, inst).course_detail(regulation, code))
