"""Metric engine — Prompts/32 §32.6 ``metric_service`` (and the ``metric_repository`` of §32.5).

1. **Registry**: ``app/core/metrics.py`` with per-module registrations (``app/services/accreditation/metrics``);
   derived keys (``depends_on``) are ordered after their dependencies (topological); params are validated against the
   definition's ``params_schema`` (top-level ``properties`` types).
2. **Compute** (job; weekly Beat and on demand): per key × (college, programme) scope; upsert ``metric_values``
   (``source='auto'``) under ``FOR UPDATE`` on the UNIQUE key (``IS NOT DISTINCT FROM`` for the NULL scope columns)
   unless an ``override`` / ``manual`` value exists (the fresh auto value is kept as ``stale_auto`` in the side store) or
   the value is verified (locked); event-fed keys (``published:*`` and the §36.5 keys pushed by modules) are read back,
   never overwritten; a period without data stores ``value = null`` with ``breakdown.reason``; five-year windows
   aggregate the yearly values (sum for counts / money, mean otherwise). Consistency checks run after a compute.
3. **Overrides** (``accreditation:override``): reason mandatory, evidence recommended; with
   ``accreditation.override_requires_verification`` (default) the proposal waits in the side store until a verifier
   (principal ``accreditation:approve`` / IQAC) verifies it; verification locks the value (``PUT`` → 409 ``LOCKED``)
   until a verifier unverifies. Manual inputs for ``manual.input`` keys only (others → 422 use an override).
4. **Drill-down**: the registered ``source_rows_query`` runs under the caller's visibility predicate (HOD → own
   department rows and a department recompute of the value; IQAC → all) with PII masked; export as xlsx (job).
5. **Trends**: period-over-period values for a key.

Event consumption (``*.stats_published`` / ``metrics.publish``): ``{metrics: {key: value}}`` upserts institution-level
``source='auto'`` rows for the payload period (``period_label``, else ``year`` → academic year ``Y-(Y+1)``, else the
current academic year), skipping unknown keys and overridden / verified rows.
"""

import time
import uuid
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select

from app.core.metrics import DRILLDOWNS, REGISTRY, MetricContext, MetricResult, Period, academic_years, normalise_period
from app.enums.accreditation import EVENT_SOURCES
from app.models.accreditation import FrameworkCriterion, MetricDefinition, MetricValue
from app.schemas.accreditation import (
    ComputeFailure,
    ComputeSummary,
    DrilldownRows,
    ManualMetricInput,
    MetricComputeRequest,
    MetricDefinitionOut,
    MetricOverride,
    MetricTrend,
    MetricValueOut,
    OverrideVerify,
)
from app.services.accreditation import metrics as _registrations  # noqa: F401  (fills REGISTRY / DRILLDOWNS)
from app.services.accreditation.common import AccreditationBase, forbidden, not_found, now_utc, rule
from app.services.accreditation.metrics.published import is_event_fed, is_manual

_SUM_UNITS = ("count", "paise")


def _dec(v: Any) -> Decimal | None:
    if v is None:
        return None
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError):
        return None


def label_for_year(year: int) -> str:
    return f"{year}-{str(year + 1)[-2:]}"


def topo(keys: list[str], defs: dict[str, MetricDefinition]) -> list[str]:
    """Keys plus their dependencies, dependencies first."""
    out: list[str] = []
    seen: set[str] = set()

    def visit(k: str, stack: tuple[str, ...] = ()) -> None:
        if k in seen or k in stack or k not in defs:
            return
        for d in defs[k].depends_on or []:
            visit(str(d), (*stack, k))
        seen.add(k)
        out.append(k)

    for k in keys:
        visit(k)
    return out


def validate_params(schema: dict[str, Any] | None, params: dict[str, Any]) -> dict[str, Any]:
    if not schema or not params:
        return dict(params or {})
    props = schema.get("properties") or {}
    types = {"integer": int, "number": (int, float), "string": str, "array": list, "boolean": bool, "object": dict}
    out: dict[str, Any] = {}
    for k, v in params.items():
        if k not in props:
            continue
        want = types.get(str(props[k].get("type")))
        if want is not None and not isinstance(v, want):  # type: ignore[arg-type]
            raise rule(f"Parameter {k} must be {props[k].get('type')}", "INVALID_PARAMS", 422)
        if isinstance(v, int | float) and props[k].get("minimum") is not None and v < props[k]["minimum"]:
            raise rule(f"Parameter {k} below minimum", "INVALID_PARAMS", 422)
        out[k] = v
    return out


class MetricService(AccreditationBase):
    # ---- definitions --------------------------------------------------------------------------------------------------
    async def definitions(self, framework: str | None = None, module: str | None = None) -> list[MetricDefinitionOut]:
        if not (self.can(self.module, "view") or self.can(self.module, "view_all") or self.can(self.module, "manage")):
            raise forbidden("accreditation:view required")
        uses: dict[str, set[str]] = {}
        from app.models.accreditation import AccreditationFramework

        for code, mk in (
            await self.db.execute(
                select(AccreditationFramework.code, FrameworkCriterion.metric_key)
                .join(FrameworkCriterion, FrameworkCriterion.framework_id == AccreditationFramework.id)
                .where(FrameworkCriterion.metric_key.is_not(None))
            )
        ).all():
            uses.setdefault(mk, set()).add(code)
        out: list[MetricDefinitionOut] = []
        for d in sorted((await self.definitions_map()).values(), key=lambda x: x.key):
            if module and d.source_module != module:
                continue
            fws = sorted(uses.get(d.key, set()))
            if framework and framework.upper() not in fws:
                continue
            kind = (
                "manual"
                if is_manual(d.computation_key)
                else "event_fed"
                if is_event_fed(d.computation_key)
                else "derived"
                if d.is_derived
                else "computed"
            )
            out.append(
                MetricDefinitionOut(
                    key=d.key,
                    name=d.name,
                    unit=d.unit,
                    source_module=d.source_module,
                    computation_key=d.computation_key,
                    is_derived=d.is_derived,
                    depends_on=[str(x) for x in d.depends_on or []],
                    params_schema=d.params_schema,
                    frameworks_using=fws,
                    registered=d.computation_key in REGISTRY,
                    kind=kind,  # type: ignore[arg-type]
                )
            )
        return out

    async def definitions_map(self) -> dict[str, MetricDefinition]:
        return await self.definitions_by_key()

    # ---- value rows -----------------------------------------------------------------------------------------------------
    async def value_row(
        self,
        key: str,
        period: str,
        college_id: uuid.UUID | None = None,
        program_id: uuid.UUID | None = None,
        *,
        lock: bool = False,
    ) -> MetricValue | None:
        stmt = select(MetricValue).where(
            MetricValue.institution_id == self.inst,
            MetricValue.metric_key == key,
            MetricValue.period_label == period,
            MetricValue.college_id.is_not_distinct_from(college_id),
            MetricValue.program_id.is_not_distinct_from(program_id),
        )
        if lock:
            stmt = stmt.with_for_update()
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def upsert_auto(
        self,
        key: str,
        period: str,
        res: MetricResult,
        *,
        college_id: uuid.UUID | None = None,
        program_id: uuid.UUID | None = None,
        job_id: uuid.UUID | None = None,
        only_if_missing: bool = False,
    ) -> MetricValue | None:
        row = await self.value_row(key, period, college_id, program_id, lock=True)
        now = now_utc()
        auto = {
            "value": str(res.value) if res.value is not None else None,
            "numerator": str(res.numerator) if res.numerator is not None else None,
            "denominator": str(res.denominator) if res.denominator is not None else None,
            "computed_at": now.isoformat(),
        }
        if row is None:
            row = MetricValue(
                institution_id=self.inst,
                college_id=college_id,
                program_id=program_id,
                metric_key=key,
                period_label=period,
            )
            self.db.add(row)
        elif only_if_missing:
            return row
        elif row.source in ("override", "manual") or row.verified_at is not None:
            m = await self.meta("override", row.id)
            m["stale_auto"] = {**auto, "breakdown": res.breakdown}
            await self.put_meta("override", row.id, m)
            return row
        row.value, row.numerator, row.denominator = _dec(res.value), _dec(res.numerator), _dec(res.denominator)
        bd = dict(res.breakdown or {})
        if res.source_rows_query:
            bd["_query"] = res.source_rows_query
        row.breakdown, row.computed_at, row.source, row.job_id = bd, now, "auto", job_id
        await self.db.flush()
        return row

    # ---- compute ----------------------------------------------------------------------------------------------------------
    async def keys_for(self, req: MetricComputeRequest) -> list[str]:
        defs = await self.definitions_map()
        if req.metric_keys:
            unknown = [k for k in req.metric_keys if k not in defs]
            if unknown:
                raise rule(f"Unknown metric keys: {', '.join(unknown)}", "UNKNOWN_METRIC", 422)
            keys = list(req.metric_keys)
        elif req.framework_code:
            fw = await self.framework(req.framework_code)
            await self.require_framework(fw)
            keys = sorted({c.metric_key for c in await self.criteria(fw.id) if c.metric_key and c.metric_key in defs})
        else:
            keys = sorted(defs)
        return topo(keys, defs)

    async def compute(self, req: MetricComputeRequest, job_id: uuid.UUID | None = None) -> ComputeSummary:
        self.require_iqac("compute")
        try:
            period = normalise_period(req.period_label)
        except ValueError as exc:
            raise rule(str(exc), "INVALID_PERIOD", 422) from exc
        started = time.monotonic()
        await self._emit("accreditation.compute_started", {"period_label": period.label}, "metric_values", None)
        keys = await self.keys_for(req)
        defs = await self.definitions_map()
        computed, skipped, failed = 0, [], []
        cache: dict[str, MetricResult] = {}
        for key in keys:
            d = defs[key]
            reg = REGISTRY.get(d.computation_key)
            if reg is None:
                failed.append(ComputeFailure(key=key, error=f"no registered function {d.computation_key}"))
                continue
            try:
                params = validate_params(d.params_schema, req.params)
                # a SAVEPOINT per key: a failing source query must not abort the compute transaction
                async with self.db.begin_nested():
                    res = await self._run(reg.fn, d, period, req.college_id, req.program_id, params, cache)
            except Exception as exc:  # noqa: BLE001 - failures are reported per key
                failed.append(ComputeFailure(key=key, error=str(exc)[:300]))
                continue
            cache[key] = res
            if is_manual(d.computation_key):
                skipped.append(key)
                continue
            await self.upsert_auto(
                key,
                period.label,
                res,
                college_id=req.college_id,
                program_id=req.program_id,
                job_id=job_id,
                only_if_missing=is_event_fed(d.computation_key),
            )
            computed += 1
        duration = int((time.monotonic() - started) * 1000)
        from app.services.accreditation.consistency_service import ConsistencyService

        checks = await ConsistencyService(self.db, self.principal, self.request, self.inst).run(
            period.label, notify=True
        )
        summary = ComputeSummary(
            period_label=period.label,
            computed=computed,
            skipped=skipped,
            failed=failed,
            duration_ms=duration,
            consistency=[c.model_dump(mode="json") for c in checks.checks],
        )
        await self._emit(
            "accreditation.compute_failed" if failed and not computed else "accreditation.compute_done",
            {"period_label": period.label, "computed": computed, "failed": len(failed)},
            "metric_values",
            None,
        )
        await self._notify(
            "accreditation.compute_done",
            [self.actor_id] if self.actor_id else await self.iqac_users(),
            {"period": period.label, "computed": computed, "failed": len(failed)},
        )
        return summary

    async def _run(
        self,
        fn: Any,
        d: MetricDefinition,
        period: Period,
        college_id: uuid.UUID | None,
        program_id: uuid.UUID | None,
        params: dict[str, Any],
        cache: dict[str, MetricResult],
        department_ids: list[uuid.UUID] | None = None,
    ) -> MetricResult:
        years = academic_years(period)
        if len(years) == 1:
            ctx = MetricContext(self.db, self.inst, period, college_id, program_id, params, cache, department_ids)
            single: MetricResult = await fn(ctx)
            return single
        # five-year window: aggregate the yearly values
        parts: list[MetricResult] = []
        for y in years:
            sub = dict(cache)  # derived keys inside a window read the window values of their dependencies
            parts.append(
                await fn(MetricContext(self.db, self.inst, y, college_id, program_id, params, sub, department_ids))
            )
        vals = [Decimal(str(p.value)) for p in parts if p.value is not None]
        if not vals:
            return MetricResult.empty("no yearly values in the five-year window")
        agg = sum(vals) if (d.unit or "") in _SUM_UNITS else sum(vals) / len(vals)
        nums = [Decimal(str(p.numerator)) for p in parts if p.numerator is not None]
        dens = [Decimal(str(p.denominator)) for p in parts if p.denominator is not None]
        return MetricResult(
            round(Decimal(agg), 4),
            sum(nums) if nums else None,
            sum(dens) if dens else None,
            {
                "yearly": {
                    y.label: (str(p.value) if p.value is not None else None) for y, p in zip(years, parts, strict=True)
                }
            },
            parts[-1].source_rows_query,
        )

    # ---- reads ---------------------------------------------------------------------------------------------------------------
    def require_reader(self) -> None:
        if not (self.can(self.module, "view") or self.can(self.module, "view_all") or self.can(self.module, "manage")):
            raise forbidden("accreditation:view required")

    async def visible_filter(self, stmt: Any, scope: str | None = None) -> Any:
        """Visibility predicate on ``metric_values`` (see ``common.py``)."""
        from sqlalchemy import false, or_

        if self.reader_all() and scope in (None, "all"):
            return stmt
        parts: list[Any] = []
        colleges = self.college_ids() if scope in (None, "college") else None
        if colleges:
            parts.append(MetricValue.college_id.in_(colleges))
        depts = await self.resolved_dept_ids() if scope in (None, "department") else None
        if depts:
            progs = await self.dept_program_ids(depts)
            parts.append(MetricValue.program_id.in_(progs or [uuid.uuid4()]))
            parts.append(MetricValue.program_id.is_(None) & MetricValue.college_id.is_(None))
        mods = self.officer_modules()
        if mods and scope in (None, "own"):
            sub = select(MetricDefinition.key).where(MetricDefinition.source_module.in_(mods))
            parts.append(MetricValue.metric_key.in_(sub) & MetricValue.program_id.is_(None))
        if self.can(self.module, "view") and scope in (None, "own") and not parts:
            # faculty: own contributions (publication / FDP counts at institution level)
            parts.append(
                MetricValue.metric_key.in_(
                    ("research.publications_per_teacher", "research.fdp_participation", "nirf.pu")
                )
                & MetricValue.program_id.is_(None)
            )
        if self.reader_all() and scope in ("department", "college"):
            return stmt.where(or_(*parts)) if parts else stmt
        return stmt.where(or_(*parts) if parts else false())

    async def values(
        self,
        *,
        period: str | None = None,
        framework: str | None = None,
        college_id: uuid.UUID | None = None,
        program_id: uuid.UUID | None = None,
        source: str | None = None,
        verified: bool | None = None,
        scope: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> tuple[list[MetricValueOut], int]:
        from sqlalchemy import func

        self.require_reader()
        stmt = select(MetricValue).where(MetricValue.institution_id == self.inst)
        if period:
            stmt = stmt.where(MetricValue.period_label == normalise_period(period).label)
        if framework:
            fw = await self.framework(framework)
            await self.require_framework(fw)
            keys = {c.metric_key for c in await self.criteria(fw.id) if c.metric_key}
            stmt = stmt.where(MetricValue.metric_key.in_(keys or {"-"}))
        if college_id:
            stmt = stmt.where(MetricValue.college_id == college_id)
        if program_id:
            stmt = stmt.where(MetricValue.program_id == program_id)
        if source:
            stmt = stmt.where(MetricValue.source == source)
        if verified is not None:
            stmt = stmt.where(MetricValue.verified_at.is_not(None) if verified else MetricValue.verified_at.is_(None))
        stmt = await self.visible_filter(stmt, scope)
        total = int((await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
        rows = list(
            (
                await self.db.execute(
                    stmt.order_by(MetricValue.metric_key, MetricValue.period_label.desc()).limit(limit).offset(offset)
                )
            )
            .scalars()
            .all()
        )
        return await self.outs(rows), total

    async def outs(self, rows: list[MetricValue]) -> list[MetricValueOut]:
        defs = await self.definitions_map()
        metas = await self.metas("override", [r.id for r in rows])
        out = []
        for r in rows:
            d = defs.get(r.metric_key)
            m = metas.get(str(r.id), {})
            out.append(
                MetricValueOut(
                    id=r.id,
                    key=r.metric_key,
                    name=d.name if d else None,
                    unit=d.unit if d else None,
                    period=r.period_label,
                    college_id=r.college_id,
                    program_id=r.program_id,
                    value=r.value,
                    numerator=r.numerator,
                    denominator=r.denominator,
                    breakdown={k: v for k, v in (r.breakdown or {}).items() if not k.startswith("_")},
                    source=r.source,
                    computed_at=r.computed_at,
                    verified=r.verified_at is not None,
                    verified_at=r.verified_at,
                    override_reason=r.override_reason,
                    pending_override=m.get("pending"),
                    stale_auto=m.get("stale_auto"),
                )
            )
        return out

    async def get(
        self, key: str, period: str, college_id: uuid.UUID | None = None, program_id: uuid.UUID | None = None
    ) -> MetricValueOut:
        self.require_reader()
        await self.definition(key)
        label = normalise_period(period).label
        stmt = await self.visible_filter(
            select(MetricValue).where(
                MetricValue.institution_id == self.inst,
                MetricValue.metric_key == key,
                MetricValue.period_label == label,
                MetricValue.college_id.is_not_distinct_from(college_id),
                MetricValue.program_id.is_not_distinct_from(program_id),
            )
        )
        row = (await self.db.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise not_found(f"Metric value {key} for {label}")
        return (await self.outs([row]))[0]

    async def trend(self, key: str, periods: list[str] | None = None) -> MetricTrend:
        self.require_reader()
        await self.definition(key)
        stmt = select(MetricValue).where(
            MetricValue.institution_id == self.inst,
            MetricValue.metric_key == key,
            MetricValue.college_id.is_(None),
            MetricValue.program_id.is_(None),
        )
        if periods:
            stmt = stmt.where(MetricValue.period_label.in_([normalise_period(p).label for p in periods]))
        stmt = await self.visible_filter(stmt)
        rows = sorted((await self.db.execute(stmt)).scalars().all(), key=lambda r: r.period_label)
        return MetricTrend(
            key=key,
            periods=[r.period_label for r in rows],
            values=[r.value for r in rows],
            sources=[r.source for r in rows],
        )

    # ---- drill-down -------------------------------------------------------------------------------------------------------
    async def drilldown(
        self,
        key: str,
        period: str,
        college_id: uuid.UUID | None = None,
        program_id: uuid.UUID | None = None,
        page: int = 1,
        per_page: int = 100,
    ) -> DrilldownRows:
        self.require_reader()
        d = await self.definition(key)
        p = normalise_period(period)
        reg = REGISTRY.get(d.computation_key)
        if reg is None:
            raise rule(f"Metric {key} has no registered computation", "NOT_REGISTERED", 422)
        depts = await self.resolved_dept_ids()
        if depts is None and not self.reader_all() and not self.college_ids() and not self.officer_modules():
            raise forbidden("Drill-down needs department, college or institution visibility")
        colleges = self.college_ids()
        if colleges and college_id is None and len(colleges) == 1:
            college_id = colleges[0]
        if colleges and college_id not in colleges:
            raise forbidden("Outside your college")
        res = await self._run(reg.fn, d, p, college_id, program_id, {}, {}, depts)
        query = res.source_rows_query
        rows: list[dict[str, Any]] = []
        if query and query in DRILLDOWNS:
            ctx = MetricContext(
                self.db, self.inst, academic_years(p)[-1] if p.kind == "five_year" else p, college_id, program_id
            )
            pred = {"department_ids": depts} if depts is not None else None
            if colleges:
                pred = {**(pred or {}), "college_ids": colleges}
            rows = await DRILLDOWNS[query](ctx, pred)
        total = len(rows)
        start = (page - 1) * per_page
        page_rows = [
            {k: (str(v) if isinstance(v, uuid.UUID | date | Decimal) else v) for k, v in r.items()}
            for r in rows[start : start + per_page]
        ]
        return DrilldownRows(
            key=key,
            period=p.label,
            query=query,
            value=_dec(res.value),
            numerator=_dec(res.numerator),
            denominator=_dec(res.denominator),
            rows=page_rows,
            total=total,
        )

    async def drilldown_rows_all(
        self, key: str, period: str, college_id: uuid.UUID | None, program_id: uuid.UUID | None
    ) -> list[dict[str, Any]]:
        out = await self.drilldown(key, period, college_id, program_id, 1, 100000)
        return out.rows

    # ---- overrides / manual / verify -------------------------------------------------------------------------------------
    async def _locked_row(
        self, key: str, period: str, college_id: uuid.UUID | None, program_id: uuid.UUID | None
    ) -> MetricValue:
        row = await self.value_row(key, period, college_id, program_id, lock=True)
        if row is None:
            row = MetricValue(
                institution_id=self.inst,
                college_id=college_id,
                program_id=program_id,
                metric_key=key,
                period_label=period,
            )
            self.db.add(row)
            await self.db.flush()
        if row.verified_at is not None:
            raise rule("The value is verified and locked for the cycle — a verifier must unverify it first", "LOCKED")
        return row

    async def override(self, key: str, body: MetricOverride) -> MetricValueOut:
        self.require_writer()
        if not (self.iqac("override") or self.can(self.module, "override")):
            raise forbidden("accreditation:override required")
        await self.definition(key)
        label = normalise_period(body.period_label).label
        if self.college_ids() and body.college_id not in (self.college_ids() or []):
            raise forbidden("Outside your college")
        row = await self._locked_row(key, label, body.college_id, body.program_id)
        proposal = {
            "value": str(body.value),
            "numerator": str(body.numerator) if body.numerator is not None else None,
            "denominator": str(body.denominator) if body.denominator is not None else None,
            "reason": body.reason,
            "evidence_ids": [str(e) for e in body.evidence_ids],
            "proposed_by": str(self.actor_id) if self.actor_id else None,
            "proposed_at": now_utc().isoformat(),
            "scope": "department" if self.dept_ids() else "institution",
        }
        m = await self.meta("override", row.id)
        needs = bool(await self.acc_setting("override_requires_verification")) or not self.iqac("override")
        if needs:
            m["pending"] = proposal
            await self.put_meta("override", row.id, m)
            await self._notify(
                "accreditation.override_pending",
                await self.iqac_users(),
                {"key": key, "period": label, "value": str(body.value), "reason": body.reason},
            )
        else:
            await self._apply_override(row, proposal, m)
        await self._audit("override_proposed" if needs else "override", "metric_value", row.id, None, proposal)
        await self._emit(
            "accreditation.metric_overridden",
            {"key": key, "period_label": label, "pending": needs, "value": str(body.value)},
            "metric_value",
            row.id,
        )
        return (await self.outs([row]))[0]

    async def _apply_override(self, row: MetricValue, proposal: dict[str, Any], m: dict[str, Any]) -> None:
        if row.source == "auto" and row.value is not None:
            m["stale_auto"] = {
                "value": str(row.value),
                "numerator": str(row.numerator) if row.numerator is not None else None,
                "denominator": str(row.denominator) if row.denominator is not None else None,
                "computed_at": row.computed_at.isoformat() if row.computed_at else None,
            }
        row.value = _dec(proposal["value"])
        row.numerator = _dec(proposal.get("numerator"))
        row.denominator = _dec(proposal.get("denominator"))
        row.source = "override"
        row.override_reason = proposal["reason"]
        row.overridden_by = uuid.UUID(proposal["proposed_by"]) if proposal.get("proposed_by") else self.actor_id
        m.pop("pending", None)
        m.setdefault("trail", []).append(
            {"at": now_utc().isoformat(), "by": str(self.actor_id), "action": "override_applied"}
        )
        await self.put_meta("override", row.id, m)
        await self.db.flush()

    async def verify(self, key: str, body: OverrideVerify) -> MetricValueOut:
        self.require_writer()
        if not self.verifier():
            raise forbidden("accreditation:approve (principal) or IQAC required")
        label = normalise_period(body.period_label).label
        row = await self.value_row(key, label, body.college_id, body.program_id, lock=True)
        if row is None:
            raise not_found(f"Metric value {key} for {label}")
        m = await self.meta("override", row.id)
        if body.action == "unverify":
            if not (self.system() or self.can(self.module, "approve")):
                raise forbidden("Only the principal (accreditation:approve) unlocks a verified value")
            row.verified_by = row.verified_at = None
        elif body.action == "reject":
            if not m.get("pending"):
                raise rule("No pending override to reject", "NO_PENDING_OVERRIDE")
            m.pop("pending", None)
        else:
            if m.get("pending"):
                await self._apply_override(row, m["pending"], m)
                m = await self.meta("override", row.id)
            row.verified_by, row.verified_at = self.actor_id, now_utc()
        m.setdefault("trail", []).append(
            {"at": now_utc().isoformat(), "by": str(self.actor_id), "action": body.action, "remarks": body.remarks}
        )
        await self.put_meta("override", row.id, m)
        await self.db.flush()
        await self._audit(f"metric_{body.action}", "metric_value", row.id, None, {"key": key, "period": label})
        if body.action == "verify":
            await self._emit(
                "accreditation.metric_verified", {"key": key, "period_label": label}, "metric_value", row.id
            )
        return (await self.outs([row]))[0]

    async def manual(self, key: str, body: ManualMetricInput) -> MetricValueOut:
        self.require_writer()
        if not (self.iqac("override") or self.can(self.module, "override")):
            raise forbidden("accreditation:override required")
        d = await self.definition(key)
        if not is_manual(d.computation_key):
            raise rule("This metric is computed — propose an override instead", "COMPUTABLE_METRIC", 422)
        label = normalise_period(body.period_label).label
        row = await self._locked_row(key, label, body.college_id, body.program_id)
        row.value, row.numerator, row.denominator = body.value, body.numerator, body.denominator
        row.breakdown = body.breakdown or {}
        row.source, row.computed_at, row.overridden_by = "manual", now_utc(), self.actor_id
        await self.db.flush()
        await self._audit("manual_input", "metric_value", row.id, None, {"key": key, "value": str(body.value)})
        await self._emit(
            "accreditation.metric_manual_input", {"key": key, "period_label": label}, "metric_value", row.id
        )
        return (await self.outs([row]))[0]

    async def pending_overrides(self) -> list[MetricValueOut]:
        if not (self.verifier() or self.can(self.module, "override")):
            raise forbidden("accreditation:override required")
        metas = await self.metas("override")
        ids = [uuid.UUID(k) for k, v in metas.items() if v.get("pending")]
        if not ids:
            return []
        stmt = await self.visible_filter(select(MetricValue).where(MetricValue.id.in_(ids)))
        return await self.outs(list((await self.db.execute(stmt)).scalars().all()))

    # ---- event consumption -------------------------------------------------------------------------------------------------
    async def consume_published(self, event_type: str, payload: dict[str, Any]) -> int:
        metrics = payload.get("metrics")
        if not isinstance(metrics, dict):
            return 0
        if payload.get("period_label"):
            label = normalise_period(str(payload["period_label"])).label
        elif payload.get("year"):
            label = label_for_year(int(payload["year"]))
        else:
            today = await self.today()
            label = label_for_year(today.year if today.month >= 6 else today.year - 1)
        defs = await self.definitions_map()
        n = 0
        for key, value in metrics.items():
            if key not in defs or isinstance(value, dict | list):
                continue
            await self.upsert_auto(
                key,
                label,
                MetricResult(
                    _dec(value), None, None, {"via": event_type, "source": EVENT_SOURCES.get(event_type, "module")}
                ),
            )
            n += 1
        return n
