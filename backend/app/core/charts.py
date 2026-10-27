"""Chart registry — Prompts/35 §35.3 / §35.6 (``chart_service`` step 1).

Every module registers its charts::

    @register_chart("fees.dues_aging", module="fees", permission=("fees:view_all", "fees:view"), kind="bar",
                    title="Dues aging", dims=["college", "department", "program", "batch"], cache_ttl=900,
                    drilldown_route="/admin/fees/invoices")
    async def dues_aging(ctx: ChartContext) -> ChartResult: ...

A provider receives a :class:`ChartContext` — the session, institution, the **resolved visibility scope** (never wider
than the caller's ``meta.visibility`` for the chart's module), the validated dims / params — and returns a
:class:`ChartResult` (series points + optional table override). The chart service wraps it into :class:`ChartData`
(series + mandatory table + drill-down + ``stale``) and caches it under ``chart:{institution}:{key}:{scope-hash}``.
Providers must narrow every query with ``ctx.where(...)`` (the scope predicate mapped onto the query's dimension
columns); ``scripts``-level guards rely on that convention, and ``ctx.where`` with no mappable column returns ``FALSE``
so an unmapped chart can never widen visibility.
"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

__all__ = [
    "CHART_KINDS",
    "CHART_REGISTRY",
    "DIMENSIONS",
    "ChartContext",
    "ChartData",
    "ChartResult",
    "ChartSpec",
    "ResolvedScope",
    "register_chart",
]

CHART_KINDS = (
    "bar",
    "line",
    "area",
    "pie",
    "donut",
    "stacked",
    "heatmap",
    "gauge",
    "table",
    "funnel",
    "number",
    "sparkline",
)
DIMENSIONS = ("college", "department", "program", "batch", "term", "period")


@dataclass
class ResolvedScope:
    """The visibility a chart query runs under (Prompts/35 "Visibility rules")."""

    level: str  # all | college | department | self | none
    module: str
    college_ids: list[uuid.UUID] = field(default_factory=list)
    department_ids: list[uuid.UUID] = field(default_factory=list)
    enrollment_ids: list[uuid.UUID] = field(
        default_factory=list
    )  # self / wards / mentees / advisees / offering students
    offering_ids: list[uuid.UUID] = field(default_factory=list)
    staff_id: uuid.UUID | None = None
    hostel_ids: list[uuid.UUID] = field(default_factory=list)
    aggregates_only: bool = False  # IQAC / auditor without <module>:view_pii
    allowed: list[str] = field(default_factory=list)

    def cache_token(self) -> str:
        parts = [
            self.level,
            ",".join(sorted(map(str, self.college_ids))),
            ",".join(sorted(map(str, self.department_ids))),
            ",".join(sorted(map(str, self.enrollment_ids)))[:4000],
            ",".join(sorted(map(str, self.offering_ids))),
            str(self.staff_id or ""),
            ",".join(sorted(map(str, self.hostel_ids))),
            "agg" if self.aggregates_only else "",
        ]
        return "|".join(parts)


@dataclass
class ChartContext:
    db: Any
    institution_id: uuid.UUID
    scope: ResolvedScope
    dims: dict[str, Any] = field(default_factory=dict)
    params: dict[str, Any] = field(default_factory=dict)
    spec: "ChartSpec | None" = None
    service: Any = None  # the AnalyticsBase that resolved the scope (people lookups, settings)

    def where(
        self,
        *,
        alias: str = "x",
        college: str | None = "college_id",
        department: str | None = "department_id",
        enrollment: str | None = None,
        staff: str | None = None,
        offering: str | None = None,
        hostel: str | None = None,
        program: str | None = "program_id",
        batch: str | None = "batch_id",
        term: str | None = None,
        institution: str = "institution_id",
    ) -> tuple[str, dict[str, Any]]:
        """SQL predicate (text + binds) for the resolved scope and the requested dims on ``alias``'s columns."""
        from app.services.analytics.predicates import scope_sql

        return scope_sql(
            self,
            alias=alias,
            cols={
                "institution": institution,
                "college": college,
                "department": department,
                "enrollment": enrollment,
                "staff": staff,
                "offering": offering,
                "hostel": hostel,
                "program": program,
                "batch": batch,
                "term": term,
            },
        )


@dataclass
class ChartResult:
    """Points ``[{label, value, series?, …}]``; ``columns`` / ``rows`` override the derived table (lists)."""

    points: list[dict[str, Any]]
    columns: list[str] | None = None
    rows: list[list[Any]] | None = None
    total: float | None = None
    drill: dict[str, str] = field(default_factory=dict)  # point field → drill-down filter name


@dataclass
class ChartData:
    key: str
    kind: str
    title: str
    series: list[dict[str, Any]]
    dims: dict[str, Any]
    table: dict[str, Any]
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    stale: bool = False
    scope: str = "all"
    drilldown: dict[str, Any] | None = None
    total: float | None = None


Provider = Callable[[ChartContext], Awaitable[ChartResult]]


@dataclass(frozen=True)
class ChartSpec:
    key: str
    module: str
    title: str
    kind: str
    permission: tuple[str, ...]  # any of "<module>:<action>"
    provider: Provider
    feature: str | None = None
    dims: tuple[str, ...] = ()
    params_schema: dict[str, Any] | None = None
    drilldown_route: str | None = None
    drilldown_rows: str | None = None  # name of a registered drill-down row query (chart_service.DRILL_QUERIES)
    cache_ttl: int = 600
    source_view: str | None = None  # read model the provider reads (stale flag); None → module stats (short ttl)
    description: str = ""
    label_field: str | None = (
        None  # drill-down filter a non-id point label maps to (category / gender / status / mode …)
    )

    def as_catalogue(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "module": self.module,
            "kind": self.kind,
            "title": self.title,
            "dims": list(self.dims),
            "params_schema": self.params_schema or {},
            "drilldown_route": self.drilldown_route,
            "feature": self.feature,
            "source_view": self.source_view,
            "description": self.description,
        }


CHART_REGISTRY: dict[str, ChartSpec] = {}


def register_chart(
    key: str,
    *,
    module: str,
    permission: tuple[str, ...] | str,
    title: str,
    kind: str = "bar",
    feature: str | None = None,
    dims: tuple[str, ...] | list[str] = (),
    params_schema: dict[str, Any] | None = None,
    drilldown_route: str | None = None,
    drilldown_rows: str | None = None,
    cache_ttl: int = 600,
    source_view: str | None = None,
    description: str = "",
    label_field: str | None = None,
) -> Callable[[Provider], Provider]:
    assert kind in CHART_KINDS, f"chart {key}: unknown kind {kind!r}"
    bad = [d for d in dims if d not in DIMENSIONS]
    assert not bad, f"chart {key}: unknown dims {bad}"
    perms = (permission,) if isinstance(permission, str) else tuple(permission)

    def deco(fn: Provider) -> Provider:
        assert key not in CHART_REGISTRY, f"duplicate chart {key}"
        CHART_REGISTRY[key] = ChartSpec(
            key=key,
            module=module,
            title=title,
            kind=kind,
            permission=perms,
            provider=fn,
            feature=feature,
            dims=tuple(dims),
            params_schema=params_schema,
            drilldown_route=drilldown_route,
            drilldown_rows=drilldown_rows,
            cache_ttl=cache_ttl if source_view else min(cache_ttl, 120),
            source_view=source_view,
            description=description,
            label_field=label_field,
        )
        return fn

    return deco
