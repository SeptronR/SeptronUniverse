"""Retro-registered Round 3–4 exports and Phase 35 chart exports — Prompts/36 §36.6 ``report_service`` step 4.

Every ``GET /<module>/reports/{kind}`` route of Rounds 3–4 becomes a :class:`~app.core.reports.ReportDef` with the same
key (``<module>.<kind>``), permission and feature; the routes stay as thin aliases that enqueue ``report.run`` (job
type ``report.run``, ``params.key = <module>.<kind>``) so existing verification scripts keep their job contract. The
providers call the module services that already apply the module's visibility (they were the bodies of the old export
jobs). Hostel registers are produced by the Phase 20 workbook writer (file-only, no inline preview).

Every Phase 35 chart is also a report (``chart.<key>``, category ``analytics``, hidden from the catalogue unless the
chart is a table) rendered through ``ChartService`` under the chart module's scope.
"""

import io
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

from app.core.reports import REPORT_REGISTRY, ReportColumn, ReportContext, ReportData, register_report

__all__ = ["LEGACY_ROUTES", "rows_data"]

# route template → kinds (``check_report_registry.py`` asserts every kind resolves to a registered key)
LEGACY_ROUTES: dict[str, tuple[str, tuple[str, ...]]] = {
    "/library/reports/{kind}": (
        "library",
        ("accession_register", "circulation", "overdue", "eresource_usage", "naac_4_2"),
    ),
    "/research/reports/{kind}": (
        "research",
        ("publications", "projects", "consultancy", "patents", "fdp", "mous", "nirf_rp"),
    ),
    "/phd/reports/{kind}": ("phd", ("scholars", "fellowships", "awards", "ugc_return", "examiners")),
    "/inventory/reports/{kind}": (
        "inventory",
        (
            "stock_ledger",
            "valuation",
            "consumption",
            "indent_cycle",
            "po_register",
            "grn_register",
            "supplier_performance",
            "asset_register",
            "depreciation",
            "hazardous",
            "audit",
        ),
    ),
    "/transport/reports/{kind}": (
        "transport",
        ("occupancy", "fees", "on_time", "cost_per_km", "compliance", "fuel", "driver_trips"),
    ),
    "/fees/reports/{report}": ("fees", ("collection", "dues", "defaulters", "scholarships", "refunds")),
    "/placement/reports/{kind}": ("placement", ("drives", "offers", "internships", "training")),
    "/hostels/reports/{kind}": (
        "hostel",
        ("occupancy", "fees", "roll_call", "leaves", "mess", "visitors", "discipline"),
    ),
    "/facilities/reports/{kind}": (
        "facilities",
        ("events", "bookings", "service_desk", "visitors", "sports", "wallet"),
    ),
    "/convocations/{id}/reports/{kind}": ("convocation", ("gowns", "seating", "attendance")),
}

_PERMS: dict[str, tuple[str, ...]] = {
    "library": ("library:view_all", "library:manage", "library:export"),
    "research": ("research:view_all", "research:export", "research:manage", "research:view"),
    "phd": ("phd:view_all", "phd:manage", "phd:export"),
    "inventory": ("inventory:view_all", "inventory:export", "inventory:manage"),
    "transport": ("transport:view_all", "transport:export", "transport:manage"),
    "fees": ("fees:view_all", "fees:export", "fees:manage"),
    "placement": ("placement:view_all", "placement:manage", "placement:export"),
    "hostel": ("hostel:view_all", "hostel:view", "hostel:manage"),
    "facilities": ("facilities:view_all", "facilities:manage", "events:view_all", "facilities:export"),
    "convocation": ("degrees:view_all", "degrees:manage", "degrees:view"),
}
_FEATURES: dict[str, str | None] = {
    "library": "library.core",
    "research": "research.publications",
    "phd": "phd.core",
    "inventory": "inventory.core",
    "transport": "transport.core",
    "fees": "fees.core",
    "placement": "placement.core",
    "hostel": "hostel.core",
    "facilities": None,
    "convocation": "degrees.convocation",
}
_VIS_MODULE = {"convocation": "degrees", "facilities": "facilities"}


def _label(k: str) -> str:
    return k.replace("_", " ").capitalize()


def rows_data(rows: list[dict[str, Any]], columns: list[str] | None = None) -> ReportData:
    """dict rows → :class:`ReportData` (column types inferred; ``*_paise`` → money; phone / email → PII)."""
    keys = columns or (list(rows[0].keys()) if rows else [])
    cols: list[ReportColumn] = []
    for k in keys:
        sample = next((r.get(k) for r in rows if r.get(k) is not None), None)
        t = "str"
        if k.endswith("_paise"):
            t = "money"
        elif k.endswith(("_pct", "pct")):
            t = "pct"
        elif isinstance(sample, bool):
            t = "bool"
        elif isinstance(sample, int):
            t = "int"
        elif isinstance(sample, float):
            t = "number"
        elif isinstance(sample, datetime):
            t = "datetime"
        elif isinstance(sample, date):
            t = "date"
        elif isinstance(sample, dict | list):
            t = "json"
        cols.append(ReportColumn(k, _label(k), type=t, pii=k in ("phone", "email", "mobile", "contact")))
    return ReportData(columns=cols, rows=[{k: r.get(k) for k in keys} for r in rows])


def _table(head: list[str], rows: list[list[Any]]) -> ReportData:
    keys = [h.lower().replace(" ", "_").replace("(", "").replace(")", "").replace("/", "_") for h in head]
    return rows_data([dict(zip(keys, r, strict=False)) for r in rows], keys)


def _xlsx_rows(content: bytes) -> ReportData:
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    ws = wb.active
    it = ws.iter_rows(values_only=True)
    head = [str(h or f"col{i}") for i, h in enumerate(next(it, ()) or ())]
    return _table(head, [list(r) for r in it])


def _year(ctx: ReportContext) -> int | None:
    y = ctx.param("year")
    return int(y) if y not in (None, "") else None


async def _library(ctx: ReportContext, kind: str) -> ReportData:
    from app.services.library.operations_service import LibraryOpsService

    head, rows = await LibraryOpsService(ctx.db, ctx.principal).report_rows(kind)
    return _table(list(head), [list(r) for r in rows])


async def _research(ctx: ReportContext, kind: str) -> ReportData:
    from app.services.research.score_service import ScoreService

    return rows_data(await ScoreService(ctx.db, ctx.principal).report_rows(kind, _year(ctx)))


async def _phd(ctx: ReportContext, kind: str) -> ReportData:
    from app.services.phd.stats_service import StatsService

    return rows_data(await StatsService(ctx.db, ctx.principal).report_rows(kind, _year(ctx)))


async def _inventory(ctx: ReportContext, kind: str) -> ReportData:
    from app.services.inventory.reports_service import InventoryReportsService

    rep = await InventoryReportsService(ctx.db, ctx.principal).report(kind, ctx.param("fy"))
    return rows_data(list(rep.rows), list(rep.columns) or None)


async def _transport(ctx: ReportContext, kind: str) -> ReportData:
    from app.services.transport.reports_service import TransportReportsService

    rep = await TransportReportsService(ctx.db, ctx.principal).report(kind)
    return rows_data(list(rep.rows), list(rep.columns) or None)


async def _fees(ctx: ReportContext, kind: str) -> ReportData:
    from app.services.fees.report_service import FeeReportService

    p: dict[str, Any] = {k: ctx.param(k) for k in ("group_by", "batch_id", "batch_year")}
    for k, src in (("date_from", "from"), ("date_to", "to")):
        v = ctx.param(src) or ctx.param(k)
        p[k] = date.fromisoformat(str(v)[:10]) if v else None
    if p.get("batch_id"):
        p["batch_id"] = uuid.UUID(str(p["batch_id"]))
    rep = await FeeReportService(ctx.db, ctx.principal).run(kind, p)
    return rows_data([r.model_dump(mode="json") for r in rep.rows])


async def _placement(ctx: ReportContext, kind: str) -> ReportData:
    from app.services.placement.stats_service import StatsService

    return _xlsx_rows(await StatsService(ctx.db, ctx.principal).report(kind))


async def _hostel(ctx: ReportContext, kind: str) -> ReportData:
    """File-only: the Phase 20 register writer uploads its own workbook; the run adopts its URL."""
    from app.services.hostel.life_service import HostelLifeService

    hid = ctx.param("hostel_id")
    out = await HostelLifeService(ctx.db, ctx.principal).report_xlsx(kind, uuid.UUID(str(hid)) if hid else None)
    data = ReportData(columns=[], rows=[])
    data.summary = {"file": {"result_url": out.get("result_url"), "rows": out.get("rows")}}
    return data


async def _facilities(ctx: ReportContext, kind: str) -> ReportData:
    from app.services.facilities.booking_service import BookingService
    from app.services.facilities.event_service import EventService
    from app.services.facilities.service_desk_service import ServiceDeskService
    from app.services.facilities.sports_service import SportsService
    from app.services.facilities.visitor_service import VisitorService
    from app.services.facilities.wallet_service import WalletService

    db, p = ctx.db, ctx.principal
    d1 = date.fromisoformat(str(ctx.param("to"))[:10]) if ctx.param("to") else date.today()
    d0 = date.fromisoformat(str(ctx.param("from"))[:10]) if ctx.param("from") else d1 - timedelta(days=30)
    rows: list[dict[str, Any]]
    if kind == "events":
        rows = [e.model_dump(mode="json") for e in await EventService(db, p).list_events()]
    elif kind == "bookings":
        rows = await BookingService(db, p).usage(
            datetime.combine(d0, datetime.min.time(), tzinfo=UTC), datetime.combine(d1, datetime.max.time(), tzinfo=UTC)
        )
    elif kind == "service_desk":
        rows = await ServiceDeskService(db, p).export_rows()
    elif kind == "visitors":
        rows = await VisitorService(db, p).register(d1)
    elif kind == "sports":
        rows = [x.model_dump(mode="json") for x in await SportsService(db, p).participation()]
    else:
        rows = [t.model_dump(mode="json") for t in await WalletService(db, p).ledger(5000)]
    return rows_data(rows)


async def _convocation(ctx: ReportContext, kind: str) -> ReportData:
    from app.services.degrees.convocation_service import ConvocationService

    cid = ctx.param("convocation_id")
    if not cid:
        from app.core.errors import APIError, ErrorCode

        raise APIError(422, ErrorCode.VALIDATION, "convocation_id is required")
    return rows_data(await ConvocationService(ctx.db, ctx.principal).report(uuid.UUID(str(cid)), kind))


_PROVIDERS: dict[str, Callable[[ReportContext, str], Awaitable[ReportData]]] = {
    "library": _library,
    "research": _research,
    "phd": _phd,
    "inventory": _inventory,
    "transport": _transport,
    "fees": _fees,
    "placement": _placement,
    "hostel": _hostel,
    "facilities": _facilities,
    "convocation": _convocation,
}

_PARAMS: dict[str, dict[str, Any]] = {
    "research": {"properties": {"year": {"type": "integer"}}},
    "phd": {"properties": {"year": {"type": "integer"}}},
    "inventory": {"properties": {"fy": {"type": "string", "pattern": "^\\d{4}-\\d{2}$"}}},
    "fees": {
        "properties": {
            "group_by": {"type": "string"},
            "batch_id": {"type": "string", "format": "uuid", "x-picker": "batch"},
            "batch_year": {"type": "integer"},
        }
    },
    "hostel": {"properties": {"hostel_id": {"type": "string", "format": "uuid", "x-picker": "hostel"}}},
    "convocation": {
        "properties": {"convocation_id": {"type": "string", "format": "uuid"}},
        "required": ["convocation_id"],
    },
}
_DATED = {"fees", "facilities"}


def _register_legacy() -> None:
    for route, (module, kinds) in LEGACY_ROUTES.items():
        provider = _PROVIDERS[module]
        for kind in kinds:
            key = f"{module}.{kind}"
            if key in REPORT_REGISTRY:
                continue

            async def run(
                ctx: ReportContext,
                _p: Callable[[ReportContext, str], Awaitable[ReportData]] = provider,
                _k: str = kind,
            ) -> ReportData:
                return await _p(ctx, _k)

            register_report(
                key,
                module=_VIS_MODULE.get(module, module),
                name=f"{_label(module)} — {_label(kind)}",
                category=module,
                description=f"Retro-registered export of {route.replace('{kind}', kind).replace('{report}', kind)}",
                permission=_PERMS[module],
                feature=_FEATURES[module],
                params_schema=dict(_PARAMS.get(module) or {}),
                formats=("xlsx",) if module == "hostel" else ("xlsx", "csv", "pdf", "json"),
                legacy_route=route,
                date_column="legacy" if module in _DATED else None,
                preview=module != "hostel",
                layout="landscape",
            )(run)


def _register_charts() -> None:
    from app.core.charts import CHART_REGISTRY
    from app.services.analytics.chart_service import ensure_catalogue

    ensure_catalogue()
    for spec in list(CHART_REGISTRY.values()):
        key = f"chart.{spec.key}"
        if key in REPORT_REGISTRY:
            continue

        async def run(ctx: ReportContext, _key: str = spec.key) -> ReportData:
            from app.services.analytics.chart_service import ChartService

            svc = ChartService(ctx.db, ctx.principal, institution_id=ctx.institution_id)
            dims = {k: v for k, v in ctx.params.items() if k.endswith("_id")}
            extra = {k: v for k, v in ctx.params.items() if k not in dims and k not in ("draft", "slow", "from", "to")}
            data = await svc.render(_key, scope=ctx.scope.level, dims=dims, params=extra, use_cache=False)
            cols = list(data.table["columns"])
            return rows_data([dict(zip(cols, r, strict=False)) for r in data.table["rows"]], cols)

        register_report(
            key,
            module=spec.module,
            name=spec.title,
            category="analytics",
            description=f"Phase 35 chart table ({spec.kind})",
            permission=tuple(spec.permission),
            feature=spec.feature,
            params_schema={
                "properties": dict((spec.params_schema or {}).get("properties", {})),
                "required": list((spec.params_schema or {}).get("required") or []),
            },
            formats=("xlsx", "csv", "pdf", "json"),
            registry_only=spec.kind != "table",
            chart_key=spec.key,
            dims=tuple(d for d in spec.dims if d in ("college", "department", "program", "batch", "term")),
        )(run)


_register_legacy()
_register_charts()
