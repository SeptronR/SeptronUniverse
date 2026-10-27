"""Report registry — Prompts/36 §36.3 / §36.6 (``report_service`` steps 1–4, ``builder_service``).

Every module registers its reports::

    @register_report("fees.collection_register", module="fees", name="Fee collection register", category="fees",
                     permission=("fees:view_all", "fees:export"), feature="fees.core", layout="ledger",
                     date_column="p.payment_date", dims=("college", "department", "program", "batch"))
    async def collection_register(ctx: ReportContext) -> ReportData: ...

or declaratively with :func:`sql_report` (a ``SELECT … WHERE {where}`` text plus the scope-column mapping — the same
shape as the Phase 35 drill-down queries). A provider receives a :class:`ReportContext` carrying the **resolved
visibility scope** of the report's source module (the Phase 35 ``ResolvedScope``: never wider than the caller's
``meta.visibility``) and must narrow every query with ``ctx.where(...)`` — an unmappable scope yields ``FALSE``, so a
report can never show rows the caller could not list. PII columns (``ReportColumn.pii``) are masked by the service
unless the caller holds ``<module>:view_pii``; statutory reports are aggregates only.

Builder models (``@register_report_model`` / :class:`ReportModel`) whitelist the base entity, columns, joins (≤ 3) and
filters the ad-hoc builder may compose — clients never send SQL.
"""

import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from app.core.charts import ResolvedScope

__all__ = [
    "COMMON_DIMS",
    "MODEL_REGISTRY",
    "REGISTER_KEYS",
    "REPORT_REGISTRY",
    "ModelColumn",
    "ModelJoin",
    "ReportColumn",
    "ReportContext",
    "ReportData",
    "ReportDef",
    "ReportModel",
    "register_report",
    "register_report_model",
    "sql_report",
]

COMMON_DIMS = ("college", "department", "program", "batch", "term")
LAYOUTS = ("portrait", "landscape", "ledger")
COLUMN_TYPES = ("str", "int", "number", "money", "pct", "date", "datetime", "bool", "json")

# register picker name (RegisterRequest.register) → report key
REGISTER_KEYS: dict[str, str] = {}


@dataclass
class ReportColumn:
    key: str
    label: str = ""
    type: str = "str"  # str | int | number | money (paise) | pct | date | datetime | bool | json
    pii: bool = False
    total: bool = False  # summed in page / grand totals (ledger layout)

    def __post_init__(self) -> None:
        if not self.label:
            self.label = self.key.replace("_", " ").capitalize()
        if self.type == "money":
            self.total = True

    def as_dict(self) -> dict[str, Any]:
        return {"key": self.key, "label": self.label, "type": self.type, "pii": self.pii, "total": self.total}


@dataclass
class ReportData:
    columns: list[ReportColumn]
    rows: list[dict[str, Any]]
    title: str | None = None
    sections: list[dict[str, Any]] = field(default_factory=list)  # [{title, columns, rows}] — multi-sheet outputs
    summary: dict[str, Any] = field(default_factory=dict)
    truncated: bool = False

    def totals(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for c in self.columns:
            if c.total:
                out[c.key] = sum((r.get(c.key) or 0) for r in self.rows if isinstance(r.get(c.key), int | float))
        return out


@dataclass
class ReportContext:
    """What a provider runs under — attribute-compatible with ``ChartContext`` for ``scope_sql``."""

    db: Any
    institution_id: uuid.UUID
    scope: ResolvedScope
    params: dict[str, Any] = field(default_factory=dict)
    dims: dict[str, Any] = field(default_factory=dict)
    principal: Any = None
    service: Any = None
    report: "ReportDef | None" = None
    limit: int | None = None
    job: Any = None  # JobContext while running as a job (progress / cancellation between chunks)

    def where(self, *, alias: str = "", cols: Mapping[str, str | None] | None = None) -> tuple[str, dict[str, Any]]:
        from app.services.analytics.predicates import scope_sql

        mapping = {"institution": "institution_id", **(cols or {})}
        return scope_sql(self, alias=alias, cols=mapping)

    def param(self, name: str, default: Any = None) -> Any:
        v = self.params.get(name)
        return default if v in (None, "") else v


Provider = Callable[[ReportContext], Awaitable[ReportData]]


@dataclass
class ReportDef:
    key: str
    module: str  # source module — visibility (``meta.visibility``) and ``<module>:view_pii`` are resolved on it
    name: str
    provider: Provider
    category: str = ""
    description: str = ""
    permission: tuple[str, ...] = ()
    feature: str | None = None
    params_schema: dict[str, Any] = field(default_factory=dict)
    formats: tuple[str, ...] = ("xlsx", "csv", "pdf", "json")
    layout: str = "portrait"
    pii_fields: tuple[str, ...] = ()
    registry_only: bool = False  # hidden from the catalogue (aliases / internal)
    statutory: dict[str, Any] | None = None
    register: str | None = None  # print-ready register name (``RegisterRequest.register``)
    legacy_route: str | None = None  # Round 3–4 ``/…/reports/{key}`` route this definition retro-registers
    chart_key: str | None = None  # Phase 35 chart rendered alongside (pdf summary) / the chart this report exports
    date_column: str | None = None
    dims: tuple[str, ...] = ()
    entity_checks: dict[str, tuple[str, Mapping[str, str | None]]] = field(default_factory=dict)
    preview: bool = True  # inline preview supported (file-only legacy providers set False)

    def __post_init__(self) -> None:
        if self.layout not in LAYOUTS:
            raise ValueError(f"report {self.key}: layout must be one of {LAYOUTS}")
        self.category = self.category or self.module
        self.params_schema = _full_schema(self.params_schema, self.date_column, self.dims)

    def as_catalogue(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "module": self.module,
            "category": self.category,
            "name": self.name,
            "description": self.description,
            "formats": list(self.formats),
            "params_schema": self.params_schema,
            "layout": self.layout,
            "register": self.register,
            "statutory": self.statutory,
            "chart_key": self.chart_key,
            "preview": self.preview,
            "pii": bool(self.pii_fields),
        }


def _full_schema(schema: dict[str, Any], date_column: str | None, dims: tuple[str, ...]) -> dict[str, Any]:
    """Merge the common parameters (period, scope dims, draft / slow switches) into a report's JSON schema."""
    props: dict[str, Any] = {}
    if date_column:
        props["from"] = {"type": "string", "format": "date", "title": "From"}
        props["to"] = {"type": "string", "format": "date", "title": "To"}
    for d in dims:
        props[f"{d}_id"] = {"type": "string", "format": "uuid", "title": d.capitalize(), "x-picker": d}
    props["draft"] = {"type": "boolean", "title": "Draft watermark", "default": False}
    props["slow"] = {"type": "boolean", "title": "Slow run (dev)", "x-dev": True}
    out = {"type": "object", **schema}
    out["properties"] = {**props, **(schema.get("properties") or {})}
    out.setdefault("required", list(schema.get("required") or []))
    return out


REPORT_REGISTRY: dict[str, ReportDef] = {}


def register_report(key: str, *, module: str, name: str, **kw: Any) -> Callable[[Provider], Provider]:
    def deco(fn: Provider) -> Provider:
        prev = REPORT_REGISTRY.get(key)
        if prev is not None and not (prev.legacy_route and not kw.get("legacy_route")):
            raise ValueError(f"report {key!r} registered twice")
        if prev is not None:  # a module definition supersedes the retro-registered export of the same key
            kw["legacy_route"] = prev.legacy_route
        d = ReportDef(key=key, module=module, name=name, provider=fn, **kw)
        REPORT_REGISTRY[key] = d
        if d.register:
            REGISTER_KEYS[d.register] = key
        return fn

    return deco


def sql_report(
    key: str,
    *,
    module: str,
    name: str,
    sql: str,
    cols: Mapping[str, str | None],
    columns: list[ReportColumn],
    filters: dict[str, str] | None = None,
    **kw: Any,
) -> ReportDef:
    """Declarative provider: ``sql`` holds ``{where}`` (scope predicate + period + dims + ``filters``)."""
    date_column = kw.get("date_column")
    param_filters = dict(filters or {})

    async def provider(ctx: ReportContext) -> ReportData:
        from sqlalchemy import text

        where, binds = ctx.where(cols=cols)
        parts = [where]
        if date_column and ctx.param("from"):
            parts.append(f"{date_column} >= :_from")
            binds["_from"] = _as_date(ctx.param("from"))
        if date_column and ctx.param("to"):
            parts.append(f"{date_column} <= :_to")
            binds["_to"] = _as_date(ctx.param("to"))
        for pname, expr in param_filters.items():
            v = ctx.param(pname)
            if v is None:
                continue
            binds[f"_p_{pname}"] = _coerce(v)
            parts.append(expr.replace(":v", f":_p_{pname}"))
        stmt = sql.format(where=" AND ".join(parts))
        if ctx.limit:
            stmt = f"SELECT * FROM ({stmt}) _r LIMIT {int(ctx.limit) + 1}"
        res = await ctx.db.execute(text(stmt), binds)
        keys = list(res.keys())
        rows = [dict(zip(keys, r, strict=False)) for r in res.all()]
        truncated = bool(ctx.limit and len(rows) > ctx.limit)
        return ReportData(columns=list(columns), rows=rows[: ctx.limit] if truncated else rows, truncated=truncated)

    register_report(key, module=module, name=name, pii_fields=tuple(c.key for c in columns if c.pii), **kw)(provider)
    return REPORT_REGISTRY[key]


def _as_date(v: Any) -> Any:
    from datetime import date

    return v if isinstance(v, date) else date.fromisoformat(str(v)[:10])


def _coerce(v: Any) -> Any:
    if isinstance(v, str) and len(v) == 36:
        try:
            return uuid.UUID(v)
        except ValueError:
            return v
    return v


# ---- builder whitelist ------------------------------------------------------------------------------------------------------
@dataclass
class ModelColumn:
    key: str
    expr: str  # SQL expression on the model's aliases (server-side only)
    label: str = ""
    type: str = "str"
    pii: bool = False
    sortable: bool = True
    aggregatable: bool = False
    filterable: bool = True

    def __post_init__(self) -> None:
        if not self.label:
            self.label = self.key.replace("_", " ").capitalize()

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "type": self.type,
            "pii": self.pii,
            "sortable": self.sortable,
            "aggregatable": self.aggregatable,
            "filterable": self.filterable,
        }


@dataclass
class ModelJoin:
    key: str
    label: str
    sql: str  # "LEFT JOIN … ON …" on the base alias
    columns: list[ModelColumn] = field(default_factory=list)


@dataclass
class ReportModel:
    key: str
    module: str
    base_entity: str
    label: str
    base_sql: str  # "FROM <table> b [JOIN …]" — scope columns refer to these aliases
    cols: Mapping[str, str | None]  # scope mapping for ``scope_sql``
    columns: list[ModelColumn]
    joins: list[ModelJoin] = field(default_factory=list)
    default_sort: str | None = None
    permission: tuple[str, ...] = ()
    feature: str | None = None
    base_where: str = "TRUE"

    def column_map(self, joins: list[str] | None = None) -> dict[str, ModelColumn]:
        out = {c.key: c for c in self.columns}
        for j in self.joins:
            if joins is None or j.key in joins:
                for c in j.columns:
                    out[f"{j.key}.{c.key}"] = c
        return out

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "module": self.module,
            "base_entity": self.base_entity,
            "label": self.label,
            "columns": [c.as_dict() for c in self.columns],
            "joins": [
                {
                    "key": j.key,
                    "label": j.label,
                    "columns": [{**c.as_dict(), "key": f"{j.key}.{c.key}"} for c in j.columns],
                }
                for j in self.joins
            ],
            "filters": [c.key for c in self.columns if c.filterable]
            + [f"{j.key}.{c.key}" for j in self.joins for c in j.columns if c.filterable],
            "default_sort": self.default_sort,
        }


MODEL_REGISTRY: dict[str, ReportModel] = {}


def register_report_model(model: ReportModel) -> ReportModel:
    if model.key in MODEL_REGISTRY:
        raise ValueError(f"report model {model.key!r} registered twice")
    MODEL_REGISTRY[model.key] = model
    return model
