"""Metric registry — Prompts/32 §32.3 / §32.6 (``metric_service`` step 1).

Every module registers the computation functions behind its ``metric_definitions.computation_key`` values::

    @register_metric("faculty.fsr", source_module="hr")
    async def fsr(ctx: MetricContext) -> MetricResult: ...

A function receives a :class:`MetricContext` (session, institution, normalised period with its date window, optional
college / programme, validated params, the values already computed in this run for ``depends_on``) and returns a
:class:`MetricResult` ``{value, numerator, denominator, breakdown, source_rows_query}``. ``source_rows_query`` names a
drill-down query registered with :func:`register_drilldown` (``(ctx, predicate) -> rows``) so the drill-down runs
under the caller's visibility predicate. Event-fed keys (``published:<key>``) and non-computable keys
(``manual.input``) are registered by the engine itself. ``scripts/check_metric_registry.py`` fails CI when a seeded
``computation_key`` has no function.
"""

import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

__all__ = [
    "DRILLDOWNS",
    "REGISTRY",
    "MetricContext",
    "MetricResult",
    "Period",
    "RegisteredMetric",
    "normalise_period",
    "register_drilldown",
    "register_metric",
]


@dataclass
class MetricResult:
    value: Decimal | float | int | None
    numerator: Decimal | float | int | None = None
    denominator: Decimal | float | int | None = None
    breakdown: dict[str, Any] = field(default_factory=dict)
    source_rows_query: str | None = None

    @classmethod
    def ratio(
        cls,
        num: float | int | Decimal,
        den: float | int | Decimal,
        *,
        pct: bool = True,
        breakdown: dict[str, Any] | None = None,
        query: str | None = None,
    ) -> "MetricResult":
        if not den:
            return cls(None, num, den, {**(breakdown or {}), "reason": "no denominator for the period"}, query)
        v = Decimal(str(num)) * (100 if pct else 1) / Decimal(str(den))
        return cls(round(v, 4), num, den, breakdown or {}, query)

    @classmethod
    def empty(cls, reason: str) -> "MetricResult":
        return cls(None, None, None, {"reason": reason})


@dataclass(frozen=True)
class Period:
    label: str  # 2025-26 | 2025 | FY2025-26 | 2020-25
    kind: str  # academic_year | calendar_year | financial_year | five_year
    start: date
    end: date

    @property
    def year(self) -> int:
        return self.start.year


@dataclass
class MetricContext:
    db: Any
    institution_id: uuid.UUID
    period: Period
    college_id: uuid.UUID | None = None
    program_id: uuid.UUID | None = None
    params: dict[str, Any] = field(default_factory=dict)
    computed: dict[str, MetricResult] = field(default_factory=dict)
    department_ids: list[uuid.UUID] | None = None  # department view (HOD drill-down recompute)


MetricFn = Callable[[MetricContext], Awaitable[MetricResult]]
DrilldownFn = Callable[[MetricContext, Any], Awaitable[list[dict[str, Any]]]]


@dataclass(frozen=True)
class RegisteredMetric:
    computation_key: str
    source_module: str
    fn: MetricFn
    params_schema: dict[str, Any] | None = None
    depends_on: tuple[str, ...] = ()


REGISTRY: dict[str, RegisteredMetric] = {}
DRILLDOWNS: dict[str, DrilldownFn] = {}


def register_metric(
    computation_key: str,
    *,
    source_module: str,
    params_schema: dict[str, Any] | None = None,
    depends_on: tuple[str, ...] = (),
) -> Callable[[MetricFn], MetricFn]:
    def deco(fn: MetricFn) -> MetricFn:
        REGISTRY[computation_key] = RegisteredMetric(computation_key, source_module, fn, params_schema, depends_on)
        return fn

    return deco


def register_drilldown(name: str) -> Callable[[DrilldownFn], DrilldownFn]:
    def deco(fn: DrilldownFn) -> DrilldownFn:
        DRILLDOWNS[name] = fn
        return fn

    return deco


_AY = re.compile(r"^(\d{4})-(\d{2})$")
_FY = re.compile(r"^FY(\d{4})-(\d{2})$", re.IGNORECASE)
_FIVE = re.compile(r"^(\d{4})-(\d{2})$")


def normalise_period(label: str, kind: str | None = None) -> Period:
    """``2025-26`` / ``2025`` / ``FY2025-26`` / ``2020-25`` (five-year window) → :class:`Period`.

    Academic years run June → May, financial years April → March (IN pack); a ``YYYY-YY`` label spanning more than one
    year is a NAAC five-year window aggregated from the yearly values.
    """
    raw = (label or "").strip()
    m = _FY.match(raw)
    if m:
        y = int(m.group(1))
        return Period(f"FY{y}-{str(y + 1)[-2:]}", "financial_year", date(y, 4, 1), date(y + 1, 3, 31))
    if raw.isdigit() and len(raw) == 4:
        y = int(raw)
        return Period(raw, "calendar_year", date(y, 1, 1), date(y, 12, 31))
    m = _AY.match(raw)
    if m:
        y = int(m.group(1))
        end2 = int(m.group(2))
        end_year = (y // 100) * 100 + end2
        if end_year < y:
            end_year += 100
        if end_year - y > 1 or kind == "five_year":
            return Period(f"{y}-{str(end_year)[-2:]}", "five_year", date(y, 6, 1), date(end_year, 5, 31))
        return Period(f"{y}-{str(y + 1)[-2:]}", "academic_year", date(y, 6, 1), date(y + 1, 5, 31))
    raise ValueError(f"Unrecognised period label {label!r} (use 2025-26, 2025, FY2025-26 or 2020-25)")


def academic_years(p: Period) -> list[Period]:
    """The yearly academic periods inside a five-year window (or the period itself)."""
    if p.kind != "five_year":
        return [p]
    return [normalise_period(f"{y}-{str(y + 1)[-2:]}") for y in range(p.start.year, p.end.year)]
