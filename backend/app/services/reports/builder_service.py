"""Ad-hoc report builder (``reports.core``) — Prompts/36 §36.6 ``builder_service`` / §36.5 ``report_model_repository``.

A :class:`~app.schemas.reports.BuilderDefinition` is compiled into a parameterised ``SELECT`` over a whitelisted
:class:`~app.core.reports.ReportModel` — never raw SQL from clients:

* only whitelisted columns / joins (≤ 3) / filter fields; unknown keys → 422; ``sum`` / ``avg`` / ``min`` / ``max``
  only on aggregatable columns;
* every row passes the model module's visibility (``scope_sql`` with the model's scope columns — an HOD's rows are
  their departments', faculty get own-offering students), PII columns masked unless ``<module>:view_pii``;
* ``LIMIT`` ≤ ``reports.max_rows`` (preview ≤ 200), ``SET LOCAL statement_timeout = 60s``;
* group-by + aggregates (count / sum / avg / min / max) with grand totals.

Saved reports (private or shared with roles) live in ``institution_settings`` category ``reports_meta`` (``saved:<id>``);
sharing needs ``reports:manage``.
"""

import uuid
from typing import Any

from sqlalchemy import select, text

from app.core.errors import APIError, ErrorCode
from app.core.jobs import enqueue
from app.core.reports import MODEL_REGISTRY, ReportColumn, ReportContext, ReportData, ReportDef, ReportModel
from app.models.platform import InstitutionSetting
from app.schemas.reports import (
    BuilderDefinition,
    BuilderPreviewOut,
    ReportModelOut,
    ReportRunOut,
    SavedReportIn,
    SavedReportOut,
)
from app.services.reports.common import ReportsBase, ensure_registry, forbidden, not_found, now_utc

__all__ = ["BuilderService"]

MAX_JOINS = 3
PREVIEW_ROWS = 200
_OPS = {
    "eq": "{c} = :{p}",
    "ne": "{c} <> :{p}",
    "gt": "{c} > :{p}",
    "gte": "{c} >= :{p}",
    "lt": "{c} < :{p}",
    "lte": "{c} <= :{p}",
    "in": "{c} = ANY(:{p})",
    "contains": "CAST({c} AS TEXT) ILIKE :{p}",
    "is_null": "{c} IS NULL",
    "not_null": "{c} IS NOT NULL",
    "between": "{c} BETWEEN :{p}_a AND :{p}_b",
}


def _invalid(msg: str, **details: Any) -> APIError:
    return APIError(422, ErrorCode.VALIDATION, msg, details)


class BuilderService(ReportsBase):
    # ---- models ---------------------------------------------------------------------------------------------------------
    async def models(self) -> list[ReportModelOut]:
        self.require_run()
        ensure_registry()
        out = []
        for m in MODEL_REGISTRY.values():
            if self.holds_any(m.permission) and await self.feature_on(m.feature):
                out.append(ReportModelOut(**m.as_dict()))
        return sorted(out, key=lambda m: m.label)

    async def model(self, key: str) -> ReportModel:
        self.require_run()
        ensure_registry()
        m = MODEL_REGISTRY.get(key)
        if m is None:
            raise not_found("Report model")
        if not self.holds_any(m.permission):
            raise forbidden(f"{' | '.join(m.permission)} required for model {key}")
        if m.feature and not await self.feature_on(m.feature):
            raise APIError(
                403, ErrorCode.FEATURE_DISABLED, f"Feature {m.feature} is not enabled", {"feature": m.feature}
            )
        return m

    async def model_out(self, key: str) -> ReportModelOut:
        return ReportModelOut(**(await self.model(key)).as_dict())

    # ---- compile ----------------------------------------------------------------------------------------------------------
    async def compile(
        self, d: BuilderDefinition, limit: int
    ) -> tuple[str, dict[str, Any], list[ReportColumn], list[str], ReportModel, Any]:
        m = await self.model(d.model_key)
        if len(d.joins) > MAX_JOINS:
            raise _invalid(f"At most {MAX_JOINS} joins", code="MAX_JOINS")
        joins = {jn.key: jn for jn in m.joins}
        bad = [k for k in d.joins if k not in joins]
        if bad:
            raise _invalid("Join not in the model whitelist", fields=bad)
        cmap = m.column_map(d.joins)
        used = {
            *d.columns,
            *d.group_by,
            *(f.field for f in d.filters),
            *(a.field for a in d.aggregates if a.field != "*"),
        }
        bad = sorted(k for k in used if k not in cmap)
        if bad:
            raise _invalid("Column not in the model whitelist", fields=bad)
        for a in d.aggregates:
            if a.fn != "count" and not cmap[a.field].aggregatable:
                raise _invalid(f"{a.field} cannot be aggregated with {a.fn}", field=a.field)
        for f in d.filters:
            if not cmap[f.field].filterable:
                raise _invalid(f"{f.field} is not filterable", field=f.field)

        scope = await self.resolve_scope(m.module, d.scope)
        ctx = ReportContext(db=self.db, institution_id=self.inst, scope=scope, principal=self.principal, service=self)
        where, binds = ctx.where(alias="", cols=m.cols)
        parts = [where, m.base_where]
        for i, f in enumerate(d.filters):
            p = f"_f{i}"
            expr = cmap[f.field].expr
            if f.op == "between":
                vals = list(f.value or [])
                if len(vals) != 2:
                    raise _invalid("between needs [from, to]", field=f.field)
                binds[f"{p}_a"], binds[f"{p}_b"] = vals[0], vals[1]
            elif f.op == "in":
                binds[p] = list(f.value or [])
            elif f.op == "contains":
                binds[p] = f"%{f.value}%"
            elif f.op not in ("is_null", "not_null"):
                binds[p] = f.value
            parts.append(_OPS[f.op].format(c=expr, p=p))

        grouped = bool(d.group_by or d.aggregates)
        out_cols: list[ReportColumn] = []
        select_list: list[str] = []
        keys = d.group_by if grouped else d.columns
        for k in keys:
            c = cmap[k]
            alias = k.replace(".", "__")
            select_list.append(f"{c.expr} AS {alias}")
            out_cols.append(ReportColumn(alias, c.label, type=c.type, pii=c.pii))
        for a in d.aggregates:
            alias = f"{a.fn}_{a.field.replace('.', '__').replace('*', 'rows')}"
            expr = "*" if a.field == "*" else cmap[a.field].expr
            fn = "COUNT" if a.fn == "count" else a.fn.upper()
            cast = (
                "::bigint"
                if a.fn in ("count", "sum") and (a.field == "*" or cmap[a.field].type in ("int", "money"))
                else ""
            )
            select_list.append(f"{fn}({expr}){cast} AS {alias}")
            ctype = "int" if a.fn == "count" else (cmap[a.field].type if a.field != "*" else "int")
            label = f"{a.fn.upper()} {cmap[a.field].label if a.field != '*' else 'rows'}"
            out_cols.append(
                ReportColumn(
                    alias,
                    label,
                    type=ctype if ctype in ("int", "money", "number", "pct") else "number",
                    total=a.fn in ("count", "sum"),
                )
            )
        joins_sql = " ".join(joins[k].sql for k in d.joins)
        sql = f"SELECT {', '.join(select_list)} {m.base_sql} {joins_sql} WHERE {' AND '.join(parts)}"
        if grouped and d.group_by:
            sql += " GROUP BY " + ", ".join(cmap[k].expr for k in d.group_by)
        order: list[str] = []
        valid_sort = {c.key for c in out_cols}
        for s in d.sort:
            alias = s.field.replace(".", "__")
            if alias not in valid_sort:
                raise _invalid("Sort field must be a selected column", field=s.field)
            order.append(f"{alias} {s.dir.upper()}")
        if not order and not grouped and m.default_sort and m.default_sort in d.columns:
            order.append(m.default_sort)
        if order:
            sql += " ORDER BY " + ", ".join(order)
        sql += f" LIMIT {int(limit)}"
        masked = self.masked_columns(m.module, out_cols)
        if scope.aggregates_only:
            masked = sorted({*masked, *(c.key for c in out_cols if c.pii)})
        return sql, binds, out_cols, masked, m, scope

    async def execute(self, d: BuilderDefinition, limit: int) -> tuple[ReportData, list[str], ReportModel, Any]:
        sql, binds, cols, masked, m, scope = await self.compile(d, limit)
        await self.db.execute(text("SET LOCAL statement_timeout = 60000"))
        res = await self.db.execute(text(sql), binds)
        keys = list(res.keys())
        rows = [dict(zip(keys, r, strict=False)) for r in res.all()]
        data = ReportData(columns=cols, rows=self.apply_mask(rows, masked), title=d.name or m.label)
        return data, masked, m, scope

    async def preview(self, d: BuilderDefinition) -> BuilderPreviewOut:
        self.require_run()
        limit = min(PREVIEW_ROWS, d.limit or PREVIEW_ROWS)
        data, masked, _m, _s = await self.execute(d, limit)
        return BuilderPreviewOut(
            columns=[c.as_dict() for c in data.columns],
            rows=data.rows,
            total=len(data.rows),
            totals=data.totals(),
            masked_fields=masked,
        )

    async def run(self, d: BuilderDefinition, fmt: str) -> ReportRunOut:
        self.require_run()
        await self.compile(d, 1)  # validate now (422 before queueing)
        job = await enqueue(
            self.db,
            self.principal,
            "report.builder_run",
            {
                "key": f"builder.{d.model_key}",
                "model_key": d.model_key,
                "definition": d.model_dump(mode="json"),
                "format": fmt,
            },
            task_name="jobs.report.builder_run",
        )
        return ReportRunOut(job_id=job.id, key=f"builder.{d.model_key}", status="queued", format=fmt)

    async def execute_job(self, job_id: uuid.UUID, definition: dict[str, Any], fmt: str) -> dict[str, Any]:
        from app.services.reports import render_service as R
        from app.services.reports.report_service import ReportService

        d = BuilderDefinition.model_validate(definition)
        max_rows = int(await self.r_setting("max_rows", 500000) or 500000)
        data, masked, m, scope = await self.execute(d, min(d.limit or max_rows, max_rows))

        async def _noop(_ctx: ReportContext) -> ReportData:
            return data

        rdef = ReportDef(
            key=f"builder.{m.key}",
            module=m.module,
            name=d.name or f"{m.label} (ad-hoc)",
            provider=_noop,
            layout="landscape",
        )
        svc = ReportService(self.db, self.principal, institution_id=self.inst)
        content, mime, ext = await svc.render(rdef, data, fmt, scope, {})
        storage_key, url = await self.upload(str(job_id), f"builder-{m.key}.{ext}", content, mime)
        await self._audit(
            "builder_run", "report", job_id, None, {"key": rdef.key, "params": {"model": m.key}, "rows": len(data.rows)}
        )
        await self._notify(
            "reports.ready",
            [self.actor_id],
            {"report": rdef.name, "key": rdef.key, "rows": len(data.rows), "url": url, "job_id": str(job_id)},
        )
        return {
            "result_url": url,
            "storage_key": storage_key,
            "rows": len(data.rows),
            "checksum": R.sha256(content),
            "format": fmt,
            "key": rdef.key,
            "masked_fields": masked,
        }

    # ---- saved reports -------------------------------------------------------------------------------------------------------
    def _saved_visible(self, v: dict[str, Any]) -> bool:
        if self.is_admin() or v.get("owner") == str(self.actor_id):
            return True
        return bool(set(v.get("shared") or []) & set(self.roles()))

    async def _saved_out(
        self, sid: str, v: dict[str, Any], names: dict[uuid.UUID, str] | None = None
    ) -> SavedReportOut:
        owner = uuid.UUID(v["owner"]) if v.get("owner") else None
        return SavedReportOut(
            id=sid,
            name=v.get("name") or "",
            definition=dict(v.get("definition") or {}),
            owner=owner,
            owner_name=(names or {}).get(owner) if owner else None,
            shared=list(v.get("shared") or []),
            created_at=self.utc(v.get("created_at")),
            updated_at=self.utc(v.get("updated_at")),
            mine=v.get("owner") == str(self.actor_id),
        )

    async def saved_list(self) -> list[SavedReportOut]:
        self.require_run()
        items = await self.metas("saved")
        vis = {k: v for k, v in items.items() if self._saved_visible(v)}
        names = await self.user_display([uuid.UUID(v["owner"]) for v in vis.values() if v.get("owner")])
        out = [await self._saved_out(k, v, names) for k, v in vis.items()]
        return sorted(out, key=lambda s: (not s.mine, s.name.lower()))

    async def saved(self, sid: str) -> tuple[dict[str, Any], SavedReportOut]:
        self.require_run()
        v = await self.meta("saved", sid)
        if not v or not self._saved_visible(v):
            raise not_found("Saved report")
        return v, await self._saved_out(sid, v)

    async def create_saved(self, body: SavedReportIn) -> SavedReportOut:
        self.require_run()
        self.require_writer()
        await self.compile(body.definition, 1)
        if body.share_with_roles and not self.is_admin():
            raise forbidden("reports:manage required to share with roles")
        sid = uuid.uuid4().hex[:16]
        now = now_utc().isoformat()
        v = {
            "name": body.name,
            "definition": body.definition.model_dump(mode="json"),
            "owner": str(self.actor_id) if self.actor_id else None,
            "shared": list(body.share_with_roles),
            "created_at": now,
            "updated_at": now,
        }
        await self.put_meta("saved", sid, v)
        await self._emit("reports.saved_report_created", {"id": sid, "name": body.name}, "report", None)
        return await self._saved_out(sid, v)

    async def update_saved(self, sid: str, body: SavedReportIn) -> SavedReportOut:
        self.require_writer()
        v, _ = await self.saved(sid)
        if v.get("owner") != str(self.actor_id) and not self.is_admin():
            raise forbidden("Only the owner or a reports manager can edit a saved report")
        await self.compile(body.definition, 1)
        if body.share_with_roles != list(v.get("shared") or []) and not self.is_admin():
            raise forbidden("reports:manage required to share with roles")
        v.update(
            name=body.name,
            definition=body.definition.model_dump(mode="json"),
            shared=list(body.share_with_roles),
            updated_at=now_utc().isoformat(),
        )
        await self.put_meta("saved", sid, v)
        return await self._saved_out(sid, v)

    async def delete_saved(self, sid: str) -> None:
        self.require_writer()
        v, _ = await self.saved(sid)
        if v.get("owner") != str(self.actor_id) and not self.is_admin():
            raise forbidden("Only the owner or a reports manager can delete a saved report")
        row = (
            await self.db.execute(
                select(InstitutionSetting).where(
                    InstitutionSetting.institution_id == self.inst,
                    InstitutionSetting.category == self.meta_category,
                    InstitutionSetting.key == f"saved:{sid}",
                )
            )
        ).scalar_one_or_none()
        if row is not None:
            await self.db.delete(row)
            await self.db.flush()

    async def share(self, sid: str, roles: list[str]) -> SavedReportOut:
        self.require_writer()
        if not self.is_admin():
            raise forbidden("reports:manage required to share saved reports")
        v, _ = await self.saved(sid)
        v["shared"], v["updated_at"] = sorted(set(roles)), now_utc().isoformat()
        await self.put_meta("saved", sid, v)
        await self._emit("reports.saved_report_shared", {"id": sid, "roles": v["shared"]}, "report", None)
        return await self._saved_out(sid, v)

    async def run_saved(self, sid: str, fmt: str) -> ReportRunOut:
        v, _ = await self.saved(sid)
        d = BuilderDefinition.model_validate({**(v.get("definition") or {}), "name": v.get("name")})
        return await self.run(d, fmt)
