"""Chart service (``analytics.core``) — Prompts/35 §35.6 chart_service.

1. Catalogue = ``CHART_REGISTRY`` filtered by the chart permission + feature for the principal.
2. ``render``: scope validated against the chart module's ``meta.visibility`` (narrowed silently), params validated
   against ``params_schema`` (422), dims applied, provider run under the predicate; returns series + **table** (always)
   + drill-down (route + filters from the clicked point) + ``stale`` (read model older than ``refresh_minutes``).
   ``format=csv`` inlines up to 5 000 rows; bigger exports run as ``analytics.chart_export`` jobs.
3. Insights: the module's charts pre-scoped to the caller's list filters (``filter[...]``).
4. Comparisons: ``params.compare`` = ``college`` | ``department`` (series per unit) and ``params.compare_period``.

Cache: ``chart:{institution}:{key}:v{module version}:{scope-hash}`` (Redis, ``cache_ttl``); domain events bump
``chartver:{institution}:{module}`` (``readmodel_service.invalidate``) so stale entries are never read again.
"""

import csv
import hashlib
import io
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text

from app.core.charts import CHART_REGISTRY, ChartContext, ChartData, ChartSpec
from app.core.errors import APIError, ErrorCode
from app.services.analytics.common import AnalyticsBase, forbidden, not_found

__all__ = ["ChartService", "DRILL_QUERIES", "ensure_catalogue"]

CSV_INLINE_LIMIT = 5000


def ensure_catalogue() -> None:
    """Import the registrations once (charts + compositions)."""
    import app.services.analytics.charts_catalogue  # noqa: F401
    import app.services.analytics.compositions  # noqa: F401


def _validate(schema: dict[str, Any] | None, params: dict[str, Any]) -> dict[str, Any]:
    """Minimal JSON-schema check (type / required / enum / minLength / format uuid) → 422 on violation."""
    if not schema:
        return dict(params)
    errors: list[str] = []
    props: dict[str, Any] = schema.get("properties", {})
    out: dict[str, Any] = {}
    for name in schema.get("required", []):
        if params.get(name) in (None, "") and props.get(name, {}).get("default") is None:
            errors.append(f"{name} is required")
    for name, value in params.items():
        spec = props.get(name)
        if spec is None:
            if name in ("compare", "compare_period", "period"):
                out[name] = value
                continue
            errors.append(f"{name} is not a parameter of this chart")
            continue
        t = spec.get("type")
        if t == "integer":
            try:
                value = int(value)
            except (TypeError, ValueError):
                errors.append(f"{name} must be an integer")
                continue
        elif t == "string":
            value = str(value)
            if len(value) < int(spec.get("minLength", 0)):
                errors.append(f"{name} is too short")
            if spec.get("format") == "uuid":
                try:
                    uuid.UUID(value)
                except ValueError:
                    errors.append(f"{name} must be a UUID")
        if "enum" in spec and value not in spec["enum"]:
            errors.append(f"{name} must be one of {spec['enum']}")
        out[name] = value
    if errors:
        raise APIError(422, ErrorCode.VALIDATION, "Invalid chart parameters", {"errors": errors})
    return out


def _pivot(points: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """``[{label, series, value}]`` → ``[{label, <series>: value}]`` + the series names."""
    if not points or "series" not in points[0]:
        keys = [k for k in (points[0] if points else {}) if k not in ("label", "_id")]
        return points, keys or ["value"]
    names: list[str] = []
    by_label: dict[Any, dict[str, Any]] = {}
    for p in points:
        s = str(p.get("series") or "—")
        if s not in names:
            names.append(s)
        row = by_label.setdefault(p["label"], {"label": p["label"], **({"_id": p["_id"]} if "_id" in p else {})})
        row[s] = (row.get(s) or 0) + float(p.get("value") or 0)
    return list(by_label.values()), names


def _flatten_single(points: list[dict[str, Any]], keys: list[str]) -> list[dict[str, Any]]:
    """A single-row multi-measure result (funnel / histogram / aging) becomes one point per measure."""
    if len(points) == 1 and len(keys) > 1 and points[0].get("label") in ("funnel", "aging", "sgpa", "ctc", "factors"):
        return [{"label": k, "value": float(points[0].get(k) or 0)} for k in keys]
    return points


# drill-down row queries — the target module's list shape (masked); ``{where}`` gets the chart scope predicate
DRILL_QUERIES: dict[str, tuple[str, dict[str, str | None], str]] = {  # (sql, scope columns, PII module)
    "students": (
        "SELECT e.id AS enrollment_id, s.registration_number, s.first_name || ' ' || COALESCE(s.last_name, '') AS name, "
        "s.gender, s.category, e.status, e.program_id, e.department_id, e.batch_id FROM student_program_enrollments e "
        "JOIN students s ON s.id = e.student_id WHERE {where} AND e.deleted_at IS NULL",
        {
            "institution": "e.institution_id",
            "college": "e.college_id",
            "department": "e.department_id",
            "program": "e.program_id",
            "batch": "e.batch_id",
            "enrollment": "e.id",
        },
        "students",
    ),
    "attendance": (
        "SELECT x.enrollment_id, s.registration_number, s.first_name || ' ' || COALESCE(s.last_name, '') AS name, x.offering_id, "
        "x.sessions_held, x.sessions_present, x.pct, x.eligibility FROM mv_attendance_term x JOIN student_program_enrollments e "
        "ON e.id = x.enrollment_id JOIN students s ON s.id = e.student_id WHERE {where}",
        {
            "institution": "x.institution_id",
            "college": "x.college_id",
            "department": "x.department_id",
            "program": "x.program_id",
            "batch": "x.batch_id",
            "term": "x.term_id",
            "enrollment": "x.enrollment_id",
            "offering": "x.offering_id",
        },
        "students",
    ),
    "fees": (
        "SELECT x.enrollment_id, s.registration_number, s.first_name || ' ' || COALESCE(s.last_name, '') AS name, "
        "x.billed_paise, x.paid_paise, x.balance_paise, x.overdue_paise FROM mv_fees_position x JOIN student_program_enrollments e "
        "ON e.id = x.enrollment_id JOIN students s ON s.id = e.student_id WHERE {where}",
        {
            "institution": "x.institution_id",
            "college": "x.college_id",
            "department": "x.department_id",
            "program": "x.program_id",
            "batch": "x.batch_id",
            "enrollment": "x.enrollment_id",
        },
        "students",
    ),
    "payments": (
        "SELECT p.id, p.receipt_number, p.payment_date, p.payment_mode, p.amount_paise, i.invoice_number FROM fee_payments p "
        "JOIN fee_invoices i ON i.id = p.invoice_id LEFT JOIN student_program_enrollments e ON e.id = i.student_program_enrollment_id "
        "WHERE {where} AND p.status IN ('success', 'reconciled')",
        {
            "institution": "p.institution_id",
            "college": "i.college_id",
            "department": "e.department_id",
            "program": "e.program_id",
            "batch": "e.batch_id",
            "enrollment": "i.student_program_enrollment_id",
        },
        "fees",
    ),
    "results": (
        "SELECT e.id AS enrollment_id, s.registration_number, tr.term_id, r.sgpa, r.cgpa, r.backlog_count, r.result_class "
        "FROM student_term_results r JOIN student_term_records tr ON tr.id = r.student_term_record_id "
        "JOIN student_program_enrollments e ON e.id = tr.student_program_enrollment_id JOIN students s ON s.id = e.student_id "
        "WHERE {where} AND r.is_current AND r.status = 'published'",
        {
            "institution": "r.institution_id",
            "college": "e.college_id",
            "department": "e.department_id",
            "program": "e.program_id",
            "batch": "e.batch_id",
            "term": "tr.term_id",
            "enrollment": "e.id",
        },
        "students",
    ),
    "staff": (
        "SELECT st.id AS staff_id, st.employee_id, st.first_name || ' ' || COALESCE(st.last_name, '') AS name, st.department_id, "
        "st.staff_category, st.status FROM staff st WHERE {where} AND st.deleted_at IS NULL AND st.status <> 'exited'",
        {
            "institution": "st.institution_id",
            "college": "st.college_id",
            "department": "st.department_id",
            "staff": "st.id",
        },
        "hr",
    ),
    "applicants": (
        "SELECT a.id, a.application_number, a.first_name || ' ' || COALESCE(a.last_name, '') AS name, a.category, a.status "
        "FROM applicants a JOIN admission_cycles c ON c.id = a.cycle_id LEFT JOIN applicant_preferences p ON p.applicant_id = a.id "
        "AND p.priority = 1 WHERE {where} AND a.deleted_at IS NULL",
        {"institution": "a.institution_id", "college": "c.college_id", "program": "p.program_id"},
        "admissions",
    ),
    "placement": (
        "SELECT da.id, s.registration_number, d.title AS drive, da.status FROM drive_applications da JOIN placement_drives d "
        "ON d.id = da.drive_id JOIN student_program_enrollments e ON e.id = da.student_program_enrollment_id "
        "JOIN students s ON s.id = e.student_id WHERE {where}",
        {
            "institution": "da.institution_id",
            "college": "e.college_id",
            "department": "e.department_id",
            "batch": "e.batch_id",
            "enrollment": "da.student_program_enrollment_id",
        },
        "students",
    ),
    "risk": (
        "SELECT f.student_program_enrollment_id AS enrollment_id, s.registration_number, f.level, f.score, f.acknowledged_at "
        "FROM risk_flags f JOIN student_program_enrollments e ON e.id = f.student_program_enrollment_id "
        "JOIN students s ON s.id = e.student_id WHERE {where}",
        {
            "institution": "f.institution_id",
            "college": "e.college_id",
            "department": "e.department_id",
            "program": "e.program_id",
            "batch": "e.batch_id",
            "term": "f.term_id",
            "enrollment": "f.student_program_enrollment_id",
        },
        "students",
    ),
}

# point fields a drill-down may filter on → qualified column per drill query
POINT_FILTERS: dict[str, dict[str, str]] = {
    "students": {"category": "s.category", "gender": "s.gender", "status": "e.status", "quota": "s.admission_quota"},
    "attendance": {"eligibility": "x.eligibility"},
    "payments": {"mode": "p.payment_mode", "series": "p.payment_mode"},
    "staff": {"cadre": "st.staff_category", "status": "st.status"},
    "applicants": {"category": "a.category", "quota": "a.quota_claimed", "status": "a.status"},
    "placement": {"status": "da.status"},
    "risk": {"level": "f.level", "series": "f.level"},
}


class ChartService(AnalyticsBase):
    # ---- catalogue ----------------------------------------------------------------------------------------------------
    async def catalogue(self, module: str | None = None) -> list[dict[str, Any]]:
        ensure_catalogue()
        out = []
        for spec in CHART_REGISTRY.values():
            if module and spec.module != module and not spec.key.startswith(f"{module}."):
                continue
            if not self.holds_any(spec.permission) or not await self.feature_on(spec.feature):
                continue
            out.append(spec.as_catalogue())
        return sorted(out, key=lambda c: c["key"])

    async def spec(self, key: str) -> ChartSpec:
        ensure_catalogue()
        spec = CHART_REGISTRY.get(key)
        if spec is None:
            raise not_found("Chart")
        if spec.feature and not await self.feature_on(spec.feature):
            raise APIError(
                403, ErrorCode.FEATURE_DISABLED, f"Feature {spec.feature} is not enabled", {"feature": spec.feature}
            )
        if not self.holds_any(spec.permission):
            raise forbidden(f"{'|'.join(spec.permission)} required")
        return spec

    # ---- render -------------------------------------------------------------------------------------------------------
    async def render(
        self,
        key: str,
        *,
        scope: str | None = None,
        dims: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        use_cache: bool = True,
    ) -> ChartData:
        spec = await self.spec(key)
        params = _validate(spec.params_schema, params or {})
        dims = {k: v for k, v in (dims or {}).items() if v not in (None, "")}
        resolved = await self.resolve_scope(spec.module, scope)
        ctx = ChartContext(
            db=self.db, institution_id=self.inst, scope=resolved, dims=dims, params=params, spec=spec, service=self
        )
        cache_key = await self._cache_key(spec, ctx)
        if use_cache:
            hit = await self._cache_get(cache_key)
            if hit is not None:
                return hit
        compare = str(params.get("compare") or "")
        if compare in ("college", "department") and spec.kind not in ("number", "gauge", "table"):
            data = await self._compare(spec, ctx, compare)
        else:
            result = await spec.provider(ctx)
            data = self._wrap(spec, ctx, result.points, result.total, result.drill)
        data.stale = await self.is_stale(spec.source_view)
        data.scope = resolved.level
        if use_cache:
            await self._cache_put(cache_key, data, spec.cache_ttl)
        return data

    def _wrap(
        self,
        spec: ChartSpec,
        ctx: ChartContext,
        points: list[dict[str, Any]],
        total: float | None,
        drill_map: dict[str, str] | None = None,
    ) -> ChartData:
        pts, keys = _pivot(points)
        pts = _flatten_single(pts, keys)
        if pts is not points and pts and "value" in pts[0] and len(keys) > 1 and pts[0]["label"] in keys:
            keys = ["value"]
        columns = ["label", *keys]
        rows = [[p.get("label"), *[p.get(k) for k in keys]] for p in pts]
        if ctx.scope.aggregates_only and spec.kind == "table":
            rows = [[None, *r[1:]] for r in rows]  # no identities for IQAC / auditor
            pts = [{**p, "label": "—", "_id": None} for p in pts]
        drill = None
        if spec.drilldown_route:
            drill = {
                "route": spec.drilldown_route,
                "key": spec.key,
                "filters": {**(ctx.dims or {})},
                "id_field": (drill_map or {}).get("_id") or None,
                "label_field": spec.label_field,
                "rows": bool(spec.drilldown_rows),
            }
        return ChartData(
            key=spec.key,
            kind=spec.kind,
            title=spec.title,
            series=pts,
            dims={**(ctx.dims or {}), "series": keys},
            table={"columns": columns, "rows": rows},
            drilldown=drill,
            total=total,
        )

    async def _compare(self, spec: ChartSpec, ctx: ChartContext, by: str) -> ChartData:
        """College vs college (university tenants) / department vs department — one series per unit."""
        dim = f"{by}_id"
        if by == "college":
            sql = "SELECT id, code FROM colleges WHERE institution_id = :i AND deleted_at IS NULL"
            ids = ctx.scope.college_ids if ctx.scope.level == "college" else None
        else:
            sql = "SELECT id, code FROM departments WHERE institution_id = :i AND deleted_at IS NULL"
            ids = ctx.scope.department_ids if ctx.scope.level == "department" else None
        if ctx.scope.level == "self":
            raise forbidden("Comparisons need a department / college / institution scope")
        units = [
            (a, b) for a, b in (await self.db.execute(text(sql), {"i": self.inst})).all() if ids is None or a in ids
        ]
        merged: list[dict[str, Any]] = []
        for uid, code in units[:12]:
            sub = ChartContext(**{**ctx.__dict__, "dims": {**ctx.dims, dim: str(uid)}})
            res = await spec.provider(sub)
            pts, keys = _pivot(res.points)
            vk = keys[0]
            for p in pts:
                merged.append({"label": p.get("label"), "series": code, "value": p.get(vk)})
        return self._wrap(spec, ctx, merged, None)

    async def table_csv(self, data: ChartData) -> str:
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(data.table["columns"])
        for r in data.table["rows"][:CSV_INLINE_LIMIT]:
            w.writerow(r)
        return buf.getvalue()

    # ---- insights -----------------------------------------------------------------------------------------------------
    async def insights(self, module: str, filters: dict[str, Any]) -> dict[str, Any]:
        cat = await self.catalogue(module)
        if not cat:
            raise forbidden(f"{module}:view required")
        dims = {
            k: v
            for k, v in filters.items()
            if k in ("college_id", "department_id", "program_id", "batch_id", "term_id", "period")
        }
        charts = []
        for c in cat[:8]:
            if c["kind"] in ("table",) or (CHART_REGISTRY[c["key"]].params_schema or {}).get("required"):
                continue
            try:
                charts.append(await self.render(c["key"], dims=dims))
            except APIError:
                continue
        return {"module": module, "filters": dims, "charts": charts}

    # ---- drill-down -------------------------------------------------------------------------------------------------
    async def drilldown(self, key: str, point: dict[str, Any], page: int = 1, size: int = 50) -> dict[str, Any]:
        spec = await self.spec(key)
        if not spec.drilldown_rows or spec.drilldown_rows not in DRILL_QUERIES:
            raise APIError(422, ErrorCode.VALIDATION, "This chart has no drill-down rows")
        sql, cols, pii_module = DRILL_QUERIES[spec.drilldown_rows]
        if not (self.can(spec.module, "view") or self.can(spec.module, "view_all") or self.can(spec.module, "manage")):
            raise forbidden(f"{spec.module}:view required")
        resolved = await self.resolve_scope(spec.module, point.get("scope"))
        dims = {
            k: point[k] for k in ("college_id", "department_id", "program_id", "batch_id", "term_id") if point.get(k)
        }
        if point.get("_id") and point.get("field") in (
            "college_id",
            "department_id",
            "program_id",
            "batch_id",
            "term_id",
        ):
            dims[str(point["field"])] = point["_id"]
        ctx = ChartContext(db=self.db, institution_id=self.inst, scope=resolved, dims=dims, spec=spec, service=self)
        full: dict[str, str | None] = {
            "institution": None,
            "college": None,
            "department": None,
            "program": None,
            "batch": None,
            "term": None,
        }
        full.update(cols)
        pred, binds = ctx.where(alias="", **full)  # type: ignore[arg-type]
        extra = ""
        for f, col in POINT_FILTERS.get(spec.drilldown_rows, {}).items():
            v = point.get(f)
            if v in (None, "", "—"):
                continue
            extra += f" AND {col} = :pf_{f}"
            binds[f"pf_{f}"] = str(v)
        if spec.drilldown_rows == "students" and not point.get("status"):
            extra += " AND e.status = 'active'"
        base = sql.format(where=pred) + extra
        total = int((await self.db.execute(text(f"SELECT COUNT(*) FROM ({base}) q"), binds)).scalar_one())
        if resolved.aggregates_only:
            return {"key": key, "total": total, "rows": [], "masked": True, "aggregates_only": True, "page": page}
        size = max(1, min(size, 200))
        rows = [
            {k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in dict(r).items()}
            for r in (await self.db.execute(text(f"{base} LIMIT {size} OFFSET {(max(page, 1) - 1) * size}"), binds))
            .mappings()
            .all()
        ]
        masked = not self.can(pii_module, "view_pii")
        if masked:
            for r in rows:
                if r.get("name"):
                    parts = str(r["name"]).split()
                    r["name"] = " ".join(p[:1] + "•" * max(len(p) - 1, 0) for p in parts)
        return {"key": key, "total": total, "rows": rows, "masked": masked, "aggregates_only": False, "page": page}

    # ---- freshness / cache --------------------------------------------------------------------------------------------
    async def is_stale(self, view: str | None) -> bool:
        if not view:
            return False
        from app.services.analytics.readmodel_service import ReadModelService

        return await ReadModelService(self.db, self.principal, self.request, self.inst).view_stale(view)

    async def _cache_key(self, spec: ChartSpec, ctx: ChartContext) -> str:
        from app.db.session import redis_client

        try:
            ver = await redis_client.get(f"chartver:{self.inst}:{spec.module}") or "0"
        except Exception:  # noqa: BLE001 - Redis down → no cache
            ver = "0"
        raw = json.dumps(
            {"s": ctx.scope.cache_token(), "d": ctx.dims, "p": ctx.params}, sort_keys=True, default=str
        ).encode()
        return f"chart:{self.inst}:{spec.key}:v{ver}:{hashlib.sha256(raw).hexdigest()[:24]}"

    async def _cache_get(self, key: str) -> ChartData | None:
        from app.db.session import redis_client

        try:
            raw = await redis_client.get(key)
        except Exception:  # noqa: BLE001
            return None
        if not raw:
            return None
        d = json.loads(raw)
        d["generated_at"] = datetime.fromisoformat(d["generated_at"])
        return ChartData(**d)

    async def _cache_put(self, key: str, data: ChartData, ttl: int) -> None:
        from app.db.session import redis_client

        payload = {**data.__dict__, "generated_at": data.generated_at.astimezone(UTC).isoformat()}
        try:
            await redis_client.set(key, json.dumps(payload, default=str), ex=max(ttl, 15))
        except Exception:  # noqa: BLE001
            return

    def etag(self, data: ChartData) -> str:
        raw = json.dumps({"t": data.table, "g": data.generated_at.isoformat()}, default=str).encode()
        return hashlib.sha256(raw).hexdigest()[:32]
