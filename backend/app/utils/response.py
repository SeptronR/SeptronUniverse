"""Response envelope — Prompts/00_PREREQUISITE_Project_Setup.md §3.8."""

from typing import Any

from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field


class PaginationMeta(BaseModel):
    page: int
    page_size: int
    total: int
    total_pages: int


class VisibilityMeta(BaseModel):
    self: bool = False
    scopes: list[str] = Field(default_factory=list)
    default: str = "self"
    pii: bool = False


def ok(
    data: Any = None,
    message: str | None = None,
    *,
    pagination: PaginationMeta | None = None,
    visibility: VisibilityMeta | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    if pagination:
        meta["pagination"] = pagination.model_dump()
    if visibility:
        meta["visibility"] = visibility.model_dump()
    if extra:
        meta.update(extra)
    return {"success": True, "data": jsonable_encoder(data), "message": message, "meta": meta}
