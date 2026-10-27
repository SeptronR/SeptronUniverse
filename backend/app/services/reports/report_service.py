"""Report service (``reports.core``) — Prompts/36 §36.6 ``report_service``.

1. Catalogue = ``REPORT_REGISTRY`` filtered by permission + feature, grouped by category, favourites / last run merged.
2. ``run``: params validated against the JSON schema (422; ``from > to`` → 422), scope params narrowed silently to the
   caller's reach; ``inline_preview`` runs the provider with ``LIMIT reports.max_inline_rows`` synchronously, otherwise
   a ``report.run`` job on the ``reports`` queue: provider → mask PII → renderer (xlsx / csv / pdf / docx / json) →
   file service (per-tenant prefix, signed URL for ``reports.retention_days``) → sha256 + row count in
   ``background_jobs.result`` → ``log_audit('reports', 'run')`` → ``reports.ready`` / ``reports.failed`` (+ deliver_to).
   Cancellation is honoured between chunks (``params.slow`` makes a dev run chunk slowly).
3. Registers are registered reports with ``register=<name>`` (ledger layout, page-wise totals).
4. Legacy ``/…/reports/{kind}`` routes call :func:`alias_job` (job type ``report.run``, ``params.key``).
5. Access log = ``audit_logs`` rows of module ``reports`` (run / download / builder_run / statutory_*).
"""

import asyncio
import contextlib
import re
import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select, text

from app.core.errors import APIError, ErrorCode
from app.core.jobs import enqueue
from app.core.reports import REGISTER_KEYS, REPORT_REGISTRY, ReportContext, ReportData, ReportDef
from app.enums.reports import REGISTERS
from app.models.platform import AuditLog, BackgroundJob
from app.schemas.reports import (
    FavouritesOut,
    RegisterOut,
    RegisterRequest,
    ReportAccessLogOut,
    ReportCatalogueOut,
    ReportLastRun,
    ReportPreview,
    ReportRunListOut,
    ReportRunOut,
    ReportRunRequest,
)
from app.services.reports import render_service as R
from app.services.reports.common import ReportsBase, ensure_registry, forbidden, not_found, now_utc

__all__ = ["ReportService", "alias_job", "alias_params", "validate_params"]

CHUNK = 500
_UUID = re.compile(r"^[0-9a-fA-F-]{36}$")


def validate_params(schema: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    """JSON-schema subset (type / format uuid|date / enum / pattern / minimum / required) → 422 with every error."""
    props: dict[str, Any] = schema.get("properties") or {}
    errors: list[str] = []
    out: dict[str, Any] = {}
    for name in schema.get("required") or []:
        if params.get(name) in (None, ""):
            errors.append(f"{name} is required")
    for name, value in params.items():
        spec = props.get(name)
        if spec is None:
            errors.append(f"{name} is not a parameter of this report")
            continue
        if value in (None, ""):
            continue
        t, fmt = spec.get("type"), spec.get("format")
        try:
            if t == "integer":
                value = int(value)
            elif t == "number":
                value = float(value)
            elif t == "boolean":
                value = value if isinstance(value, bool) else str(value).lower() in ("1", "true", "yes", "on")
            elif t == "string":
                value = str(value)
                if fmt == "uuid" and not _UUID.match(value):
                    raise ValueError("must be a UUID")
                if fmt == "date":
                    date.fromisoformat(value[:10])
                    value = value[:10]
                if spec.get("pattern") and not re.match(spec["pattern"], value):
                    raise ValueError(f"must match {spec['pattern']}")
        except ValueError as exc:
            errors.append(f"{name} {exc}" if str(exc).startswith("must") else f"{name} has an invalid value")
            continue
        if "enum" in spec and value not in spec["enum"]:
            errors.append(f"{name} must be one of {spec['enum']}")
            continue
        if "minimum" in spec and isinstance(value, int | float) and value < spec["minimum"]:
            errors.append(f"{name} must be ≥ {spec['minimum']}")
            continue
        out[name] = value
    if out.get("from") and out.get("to") and str(out["from"]) > str(out["to"]):
        errors.append("from must not be after to")
    if errors:
        raise APIError(422, ErrorCode.VALIDATION, "Invalid report parameters", {"errors": errors})
    return out


async def alias_params(db: Any, principal: Any, key: str, params: dict[str, Any], fmt: str = "xlsx") -> dict[str, Any]:
    """Round 3–4 ``/…/reports/{kind}`` routes → the ``report.run`` job params (validated and permission-checked now;
    the module routes enqueue job type ``report.run`` with them)."""
    svc = ReportService(db, principal)
    d = await svc.report_def(key)
    svc.require_run()
    clean = {k: (str(v) if isinstance(v, uuid.UUID | date) else v) for k, v in params.items() if v not in (None, "")}
    clean = validate_params(d.params_schema, clean)
    await svc.remember_run(key, None)
    return {"key": key, "params": clean, "format": fmt if fmt in d.formats else d.formats[0], "alias": True}


async def alias_job(db: Any, principal: Any, key: str, params: dict[str, Any], fmt: str = "xlsx") -> BackgroundJob:
    """Enqueue the ``report.run`` job of a legacy alias (routes whose ``_job`` helper returns the row id)."""
    return await enqueue(
        db, principal, "report.run", await alias_params(db, principal, key, params, fmt), task_name="jobs.report.run"
    )


class ReportService(ReportsBase):
    # ---- catalogue ------------------------------------------------------------------------------------------------------
    async def catalogue(
        self, module: str | None = None, category: str | None = None, q: str | None = None
    ) -> list[ReportCatalogueOut]:
        self.require_catalogue()
        ensure_registry()
        prefs = await self.prefs()
        favs = set(prefs.get("favourites") or [])
        last = await self._last_runs()
        out: list[ReportCatalogueOut] = []
        needle = (q or "").lower().strip()
        for d in REPORT_REGISTRY.values():
            if d.registry_only and d.key not in favs:
                continue
            if module and d.module != module and not d.key.startswith(f"{module}."):
                continue
            if category and d.category != category:
                continue
            if needle and needle not in f"{d.key} {d.name} {d.description}".lower():
                continue
            if d.statutory or not await self.visible_def(d) or not await self.feature_on(d.feature):
                continue
            item = ReportCatalogueOut(**d.as_catalogue(), favourite=d.key in favs, last_run=last.get(d.key))
            out.append(item)
        return sorted(out, key=lambda c: (not c.favourite, c.category, c.name))

    async def _last_runs(self) -> dict[str, ReportLastRun]:
        if self.actor_id is None:
            return {}
        rows = (
            await self.db.execute(
                select(BackgroundJob)
                .where(
                    BackgroundJob.institution_id == self.inst,
                    BackgroundJob.job_type == "report.run",
                    BackgroundJob.requested_by == self.actor_id,
                )
                .order_by(BackgroundJob.created_at.desc())
                .limit(200)
            )
        ).scalars()
        out: dict[str, ReportLastRun] = {}
        for j in rows:
            k = str((j.params or {}).get("key") or "")
            if k and k not in out:
                out[k] = ReportLastRun(
                    job_id=j.id, status=j.status, created_at=j.created_at, rows=(j.result or {}).get("rows")
                )
        return out

    # ---- produce --------------------------------------------------------------------------------------------------------
    async def prepare(
        self, d: ReportDef, params: dict[str, Any], scope: str | None = None
    ) -> tuple[Any, dict[str, Any]]:
        resolved = await self.scope_for(d, scope)
        clean = validate_params(d.params_schema, {k: v for k, v in (params or {}).items() if v not in (None, "")})
        clean = await self.narrow_params(resolved, clean)
        return resolved, clean

    async def produce(
        self,
        d: ReportDef,
        params: dict[str, Any],
        scope: str | None = None,
        *,
        limit: int | None = None,
        job: Any = None,
    ) -> tuple[ReportData, Any, list[str], dict[str, Any]]:
        """→ (data with PII masked, resolved scope, masked column keys, validated params)."""
        resolved, clean = await self.prepare(d, params, scope)
        dims = {
            k: v for k, v in clean.items() if k in ("college_id", "department_id", "program_id", "batch_id", "term_id")
        }
        ctx = ReportContext(
            db=self.db,
            institution_id=self.inst,
            scope=resolved,
            params=clean,
            dims=dims,
            principal=self.principal,
            service=self,
            report=d,
            limit=limit,
            job=job,
        )
        for pname, (sql, cols) in d.entity_checks.items():
            if clean.get(pname):
                where, binds = ctx.where(alias="", cols=cols)
                found = (await self.db.execute(text(sql.format(where=where)), {**binds, "id": clean[pname]})).first()
                if found is None:
                    raise not_found(pname.removesuffix("_id").replace("_", " ").capitalize())
        data = await d.provider(ctx)
        masked = self.masked_columns(d.module, data.columns)
        if resolved.aggregates_only:
            masked = sorted({*masked, *(c.key for c in data.columns if c.pii)})
        data.rows = self.apply_mask(data.rows, masked)
        for s in data.sections:
            s["rows"] = self.apply_mask(list(s.get("rows") or []), masked)
        return data, resolved, masked, clean

    # ---- run ----------------------------------------------------------------------------------------------------------------
    async def run(self, body: ReportRunRequest) -> ReportRunOut:
        self.require_run()
        d = await self.report_def(body.key)
        if body.format not in d.formats and not body.inline_preview:
            raise APIError(
                422, ErrorCode.VALIDATION, f"{body.key} renders {', '.join(d.formats)}", {"formats": list(d.formats)}
            )
        if body.deliver_to and body.deliver_to.emails and d.pii_fields:
            raise APIError(
                422,
                ErrorCode.VALIDATION,
                "Reports with personal data cannot be sent to external emails",
                {"code": "PII_EMAIL"},
            )
        if body.inline_preview:
            if not d.preview:
                raise APIError(422, ErrorCode.VALIDATION, "This report has no inline preview — run it as a job")
            limit = int(await self.r_setting("max_inline_rows", 2000) or 2000)
            data, resolved, masked, clean = await self.produce(d, body.params, body.scope, limit=limit)
            await self._audit("preview", "report", None, None, {"key": d.key, "params": clean})
            return ReportRunOut(
                key=d.key,
                status="preview",
                format=body.format,
                params=clean,
                rows=len(data.rows),
                scope=resolved.level,
                preview=ReportPreview(
                    columns=[c.as_dict() for c in data.columns],
                    rows=data.rows,
                    totals=data.totals(),
                    truncated=data.truncated,
                    masked_fields=masked,
                ),
            )
        resolved, clean = await self.prepare(d, body.params, body.scope)
        job = await enqueue(
            self.db,
            self.principal,
            "report.run",
            {
                "key": d.key,
                "params": clean,
                "format": body.format,
                "scope": body.scope,
                "deliver_to": body.deliver_to.model_dump(mode="json") if body.deliver_to else None,
            },
            task_name="jobs.report.run",
        )
        await self._emit("reports.run_started", {"job_id": str(job.id), "key": d.key}, "background_job", job.id)
        await self.remember_run(d.key, job.id)
        return ReportRunOut(
            job_id=job.id, key=d.key, status="queued", format=body.format, params=clean, scope=resolved.level
        )

    async def execute(
        self,
        job_id: uuid.UUID,
        key: str,
        params: dict[str, Any],
        fmt: str,
        scope: str | None = None,
        deliver_to: dict[str, Any] | None = None,
        job: Any = None,
        schedule_id: str | None = None,
    ) -> dict[str, Any]:
        """Body of the ``report.run`` job (runs as the requester — schedules enqueue one job per recipient)."""
        d = await self.report_def(key)
        self.require_run()
        try:
            max_rows = int(await self.r_setting("max_rows", 500000) or 500000)
            data, resolved, masked, clean = await self.produce(d, params, scope, limit=max_rows, job=job)
            await self._chunks(data, job, bool(clean.get("slow")))
            if data.summary.get("file"):  # file-only legacy provider (writer uploaded its own workbook)
                f = data.summary["file"]
                result = {"result_url": f.get("result_url"), "rows": f.get("rows"), "key": key, "format": "xlsx"}
            else:
                content, mime, ext = await self.render(d, data, fmt, resolved, clean)
                stem = re.sub(r"[^A-Za-z0-9_.-]+", "-", f"{key}-{(await self.today()).isoformat()}")
                storage_key, url = await self.upload(str(job_id), f"{stem}.{ext}", content, mime)
                result = {
                    "result_url": url,
                    "storage_key": storage_key,
                    "rows": len(data.rows),
                    "checksum": R.sha256(content),
                    "bytes": len(content),
                    "format": fmt,
                    "key": key,
                    "scope": resolved.level,
                    "masked_fields": masked,
                    "truncated": data.truncated,
                }
            await self._audit(
                "run", "report", job_id, None, {"key": key, "params": clean, "format": fmt, "rows": result["rows"]}
            )
            if schedule_id is None:
                await self._notify(
                    "reports.ready",
                    [self.actor_id],
                    {
                        "report": d.name,
                        "key": key,
                        "rows": result["rows"],
                        "url": result["result_url"],
                        "job_id": str(job_id),
                    },
                )
            if deliver_to:
                result["delivery"] = await self.deliver(d, result, deliver_to)
            await self._emit(
                "reports.ready", {"job_id": str(job_id), "key": key, "rows": result["rows"]}, "background_job", job_id
            )
            return result
        except Exception as exc:
            from app.core.jobs import JobCancelled

            if isinstance(exc, JobCancelled):
                await self._emit("reports.cancelled", {"job_id": str(job_id), "key": key}, "background_job", job_id)
                raise
            await self._notify(
                "reports.failed",
                [self.actor_id],
                {"report": d.name, "key": key, "error": str(exc)[:300], "job_id": str(job_id)},
            )
            await self._emit(
                "reports.failed", {"job_id": str(job_id), "key": key, "error": str(exc)[:300]}, "background_job", job_id
            )
            raise

    async def _chunks(self, data: ReportData, job: Any, slow: bool) -> None:
        """Progress + cancellation between chunks (the provider already streamed under the row cap)."""
        if job is None:
            return
        total = max(len(data.rows), 1)
        for i in range(0, total, CHUNK):
            if slow:
                await asyncio.sleep(2)
            await job.progress(
                self.db, min(95, int(100 * (i + CHUNK) / total)), f"{min(i + CHUNK, total)} / {total} rows"
            )

    async def render(
        self, d: ReportDef, data: ReportData, fmt: str, resolved: Any, params: dict[str, Any]
    ) -> tuple[bytes, str, str]:
        title = data.title or d.name
        header = await self.header(title, resolved, params)
        sections = [{"title": title, "columns": data.columns, "rows": data.rows, "totals": data.totals()}]
        sections += [{**s, "totals": {}} for s in data.sections]
        if fmt == "xlsx":
            return R.render_xlsx(sections, header), R.CONTENT_TYPES["xlsx"], "xlsx"
        if fmt == "csv":
            return R.render_csv(data.columns, data.rows), R.CONTENT_TYPES["csv"], "csv"
        if fmt == "json":
            return (
                R.render_json(data.columns, data.rows, {"key": d.key, "params": params}),
                R.CONTENT_TYPES["json"],
                "json",
            )
        if fmt == "docx":
            return (
                R.render_docx(title, sections, [header["scope"] or "", header["generated_on"]]),
                R.CONTENT_TYPES["docx"],
                "docx",
            )
        summary = [(k, v) for k, v in data.summary.items() if not isinstance(v, dict | list)]
        return (
            R.render_pdf(
                title,
                data.columns,
                data.rows,
                layout=d.layout,
                header=header,
                sections=data.sections,
                summary=summary or None,
            ),
            R.CONTENT_TYPES["pdf"],
            "pdf",
        )

    async def deliver(self, d: ReportDef, result: dict[str, Any], deliver_to: dict[str, Any]) -> list[str]:
        users = [uuid.UUID(str(u)) for u in deliver_to.get("user_ids") or []]
        emails = [str(e) for e in deliver_to.get("emails") or []]
        ctx = {"report": d.name, "key": d.key, "rows": result.get("rows"), "url": result.get("result_url")}
        if users:
            await self._notify("reports.scheduled_delivery", users, ctx)
        if emails and not d.pii_fields:
            from app.core.notifications.notify import notify_event

            await notify_event(
                self.db,
                self.inst,
                "reports.scheduled_delivery",
                audience={"direct_contacts": [{"channel": "email", "to": e} for e in emails]},
                context=ctx,
                actor_user_id=self.actor_id,
            )
        return [str(u) for u in users] + emails

    # ---- runs ----------------------------------------------------------------------------------------------------------------
    async def run_out(self, j: BackgroundJob, names: dict[uuid.UUID, str] | None = None) -> ReportRunOut:
        p, r = dict(j.params or {}), dict(j.result or {})
        return ReportRunOut(
            job_id=j.id,
            key=str(p.get("key") or p.get("code") or p.get("model_key") or j.job_type),
            status=j.status,
            format=p.get("format"),
            params=dict(p.get("params") or {}),
            rows=r.get("rows"),
            result_url=None if r.get("purged") else (j.result_url or r.get("result_url")),
            checksum=r.get("checksum"),
            requested_by=j.requested_by,
            requested_by_name=(names or {}).get(j.requested_by) if j.requested_by else None,
            created_at=j.created_at,
            finished_at=j.finished_at,
            error=j.error,
            purged=bool(r.get("purged")),
            scope=r.get("scope"),
        )

    async def runs(
        self,
        *,
        mine: bool,
        key: str | None = None,
        status: str | None = None,
        requested_by: uuid.UUID | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        page: int = 1,
        size: int = 50,
    ) -> ReportRunListOut:
        self.require_catalogue()
        stmt = self.runs_query(mine)
        if key:
            stmt = stmt.where(BackgroundJob.params["key"].astext == key)
        if status:
            stmt = stmt.where(BackgroundJob.status == status)
        if requested_by:
            stmt = stmt.where(BackgroundJob.requested_by == requested_by)
        if date_from:
            stmt = stmt.where(func.date(BackgroundJob.created_at) >= date_from)
        if date_to:
            stmt = stmt.where(func.date(BackgroundJob.created_at) <= date_to)
        total = int((await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
        rows = list(
            (
                await self.db.execute(
                    stmt.order_by(BackgroundJob.created_at.desc()).offset((page - 1) * size).limit(size)
                )
            ).scalars()
        )
        names = await self.user_display([j.requested_by for j in rows])
        return ReportRunListOut(items=[await self.run_out(j, names) for j in rows], total=total)

    async def get_run(self, job_id: uuid.UUID) -> ReportRunOut:
        self.require_catalogue()
        j = await self.run_row(job_id)
        return await self.run_out(j, await self.user_display([j.requested_by]))

    async def cancel(self, job_id: uuid.UUID) -> ReportRunOut:
        from app.services.job_service import JobService

        self.require_run()
        j = await self.run_row(job_id)
        if j.requested_by != self.actor_id and not self.is_admin():
            raise forbidden("Only the requester or a reports manager can cancel a run")
        await JobService(self.db, self.principal).cancel(j.id)
        await self.db.refresh(j)
        return await self.run_out(j)

    async def download(self, job_id: uuid.UUID) -> str:
        """Signed URL of the run's file (audited); 410 once the retention purge removed it."""
        self.require_catalogue()
        j = await self.run_row(job_id)
        r = dict(j.result or {})
        if r.get("purged"):
            raise APIError(
                410,
                ErrorCode.GONE,
                "The report file was purged after the retention period",
                {"checksum": r.get("checksum")},
            )
        if j.status != "succeeded" or not (j.result_url or r.get("result_url")):
            raise APIError(409, ErrorCode.CONFLICT, f"Run is {j.status}")
        url = str(j.result_url or r.get("result_url"))
        if r.get("storage_key"):
            from app.core.files import get_storage

            url = get_storage().signed_url(str(r["storage_key"]), 3600)
        await self._audit("download", "report", j.id, None, {"key": (j.params or {}).get("key")})
        await self._emit(
            "reports.downloaded", {"job_id": str(j.id), "key": (j.params or {}).get("key")}, "background_job", j.id
        )
        return url

    # ---- favourites -----------------------------------------------------------------------------------------------------------
    async def favourites(self) -> FavouritesOut:
        self.require_catalogue()
        p = await self.prefs()
        return FavouritesOut(keys=list(p.get("favourites") or []), recent=list(p.get("recent") or []))

    async def toggle_favourite(self, key: str) -> FavouritesOut:
        self.require_catalogue()
        await self.report_def(key)
        p = await self.prefs()
        favs = list(p.get("favourites") or [])
        if key in favs:
            favs.remove(key)
        else:
            favs.insert(0, key)
        p["favourites"] = favs[:100]
        await self.put_prefs(p)
        return FavouritesOut(keys=favs, recent=list(p.get("recent") or []))

    # ---- registers ------------------------------------------------------------------------------------------------------------
    async def registers(self) -> list[RegisterOut]:
        self.require_catalogue()
        ensure_registry()
        out = []
        for name in REGISTERS:
            key = REGISTER_KEYS.get(name)
            d = REPORT_REGISTRY.get(key or "")
            if d is None:
                continue
            ok_ = await self.visible_def(d) and await self.feature_on(d.feature)
            out.append(
                RegisterOut(
                    register_name=name,
                    key=d.key,
                    name=d.name,
                    params_schema=d.params_schema,
                    module=d.module,
                    available=ok_,
                )
            )
        return out

    async def run_register(self, body: RegisterRequest) -> ReportRunOut:
        ensure_registry()
        key = REGISTER_KEYS.get(body.register_name)
        if key is None:
            raise not_found("Register")
        params = dict(body.scope)
        if body.period:
            if body.period.from_:
                params["from"] = body.period.from_.isoformat()
            if body.period.to:
                params["to"] = body.period.to.isoformat()
        out = await self.run(ReportRunRequest(key=key, params=params, format=body.format))
        if out.job_id:
            await self._emit(
                "reports.register_generated",
                {"register": body.register_name, "job_id": str(out.job_id)},
                "background_job",
                out.job_id,
            )
        return out

    # ---- access log ----------------------------------------------------------------------------------------------------------
    async def access_log(
        self,
        key: str | None = None,
        user_id: uuid.UUID | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        limit: int = 200,
    ) -> list[ReportAccessLogOut]:
        if not (self.is_admin() or self.can("audit_logs", "view_all")):
            raise forbidden("reports:manage or audit_logs:view_all required")
        stmt = select(AuditLog).where(AuditLog.institution_id == self.inst, AuditLog.module == "reports")
        if key:
            stmt = stmt.where(AuditLog.new_values["key"].astext == key)
        if user_id:
            stmt = stmt.where(AuditLog.user_id == user_id)
        if date_from:
            stmt = stmt.where(AuditLog.occurred_at >= date_from)
        if date_to:
            stmt = stmt.where(AuditLog.occurred_at < date_to + timedelta(days=1))
        rows = list((await self.db.execute(stmt.order_by(AuditLog.occurred_at.desc()).limit(limit))).scalars())
        names = await self.user_display([r.user_id for r in rows])
        return [
            ReportAccessLogOut(
                id=r.id,
                at=r.occurred_at,
                user_id=r.user_id,
                user_name=names.get(r.user_id) if r.user_id else None,
                action=r.action,
                key=(r.new_values or {}).get("key") or (r.new_values or {}).get("code"),
                params=dict((r.new_values or {}).get("params") or {}),
                record_id=r.record_id,
            )
            for r in rows
        ]

    # ---- retention -----------------------------------------------------------------------------------------------------------
    async def retention_purge(self) -> int:
        """Delete files of runs older than ``reports.retention_days``; the run row keeps its checksum (download → 410)."""
        from app.core.files import get_storage

        days = int(await self.r_setting("retention_days", 30) or 30)
        cutoff = now_utc() - timedelta(days=days)
        rows = (
            await self.db.execute(
                select(BackgroundJob).where(
                    BackgroundJob.institution_id == self.inst,
                    BackgroundJob.job_type.in_(("report.run", "report.builder_run", "report.statutory_pack")),
                    BackgroundJob.created_at < cutoff,
                    BackgroundJob.status == "succeeded",
                )
            )
        ).scalars()
        storage = get_storage()
        n = 0
        for j in rows:
            r = dict(j.result or {})
            if r.get("purged"):
                continue
            if r.get("storage_key"):
                with contextlib.suppress(Exception):  # already gone is fine
                    await storage.delete(str(r["storage_key"]))
            r["purged"], r["purged_at"] = True, now_utc().isoformat()
            j.result, j.result_url = r, None
            n += 1
        await self.db.flush()
        return n
