"""Pagination query params — Prompts/00_PREREQUISITE_Project_Setup.md §3.8.

API conventions enforced everywhere: ``page/page_size <= 200``, ``sort=-field``, ``filter[field][op]=value``
(``eq, ne, in, lt, lte, gt, gte, like``), ``include=`` expansions, ``fields=`` sparse fields.
"""

from typing import Any

from fastapi import Query, Request
from pydantic import BaseModel

FILTER_OPS = {"eq", "ne", "in", "lt", "lte", "gt", "gte", "like"}


class PageParams(BaseModel):
    page: int = 1
    page_size: int = 25
    sort: str | None = None

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


def page_params(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    sort: str | None = Query(None, pattern=r"^-?[a-z_]+$"),
) -> PageParams:
    return PageParams(page=page, page_size=page_size, sort=sort)


def parse_filters(request: Request) -> dict[str, dict[str, Any]]:
    """Parse ``filter[status][eq]=active&filter[amount][gte]=100`` into ``{field: {op: value}}``."""
    filters: dict[str, dict[str, Any]] = {}
    for key, value in request.query_params.multi_items():
        if not key.startswith("filter[") or not key.endswith("]"):
            continue
        parts = key[7:-1].split("][")
        field = parts[0]
        op = parts[1] if len(parts) > 1 else "eq"
        if op not in FILTER_OPS:
            continue
        filters.setdefault(field, {})[op] = value.split(",") if op == "in" else value
    return filters
