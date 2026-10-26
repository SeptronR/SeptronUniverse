"""Event-fed and non-computable metric handlers (registered in ``app/core/metrics.py``).

* ``published:<key>`` — modules push precomputed values (``research.stats_published`` with ``nirf.pu / qp / ipr /
  fppp`` and the NAAC 3.x keys, ``phd.stats_published`` with ``nirf.gphd / faculty.phd_guides / research.phd_awarded``,
  ``placement.stats_published``, ``alumni.stats_published``, library ``metrics.publish``); the consumer in
  ``metric_service`` upserts them into ``metric_values``. Computing such a key reads the pushed row back (the engine
  never overwrites it), or reports ``awaiting <module>.stats_published``.
* ``manual.input`` — non-computable keys (green / energy audit outcomes, PCS facilities, MOOC completions): the value is
  entered through ``PUT /accreditation/metrics/{key}/manual``.
"""

from app.core.metrics import REGISTRY, MetricContext, MetricResult, RegisteredMetric
from app.enums.accreditation import METRIC_DEFINITIONS, PUBLISHED_SEED_KEYS

_SOURCES = {
    "research": "research.stats_published",
    "phd": "phd.stats_published",
    "placement": "placement.stats_published",
    "alumni": "alumni.stats_published",
    "library": "metrics.publish",
}


async def read_back(ctx: MetricContext, key: str) -> MetricResult | None:
    from sqlalchemy import select

    from app.models.accreditation import MetricValue

    row = (
        await ctx.db.execute(
            select(MetricValue).where(
                MetricValue.institution_id == ctx.institution_id,
                MetricValue.metric_key == key,
                MetricValue.period_label == ctx.period.label,
                MetricValue.college_id.is_not_distinct_from(ctx.college_id),
                MetricValue.program_id.is_not_distinct_from(ctx.program_id),
            )
        )
    ).scalar_one_or_none()
    if row is None or row.value is None:
        return None
    return MetricResult(row.value, row.numerator, row.denominator, dict(row.breakdown or {}))


def _published(key: str, module: str) -> RegisteredMetric:
    async def fn(ctx: MetricContext) -> MetricResult:
        got = await read_back(ctx, key)
        return got or MetricResult.empty(f"awaiting {_SOURCES.get(module, module + '.stats_published')}")

    return RegisteredMetric(f"published:{key}", module, fn)


async def _manual(ctx: MetricContext) -> MetricResult:
    return MetricResult.empty("manual input required")


REGISTRY["manual.input"] = RegisteredMetric("manual.input", "accreditation", _manual)

for _key, _name, _unit, _module, _ck, _ps, _dep in METRIC_DEFINITIONS:
    if _ck.startswith("published:"):
        REGISTRY[_ck] = _published(_ck.split(":", 1)[1], _module)

# §36.5 seed rows carry ``computation_key = key``; the event-fed ones resolve to the read-back handler
_SEED_MODULES = {
    "research.publications_per_teacher": "research",
    "research.grants_amount": "research",
    "research.consultancy_revenue": "research",
    "research.patents": "research",
    "research.fdp_participation": "research",
    "nirf.gphd": "phd",
    "placement.placed_pct": "placement",
    "nirf.gms": "placement",
    "students.higher_studies_pct": "placement",
    "academics.internships_pct": "placement",
}
for _key in PUBLISHED_SEED_KEYS:
    REGISTRY[_key] = RegisteredMetric(_key, _SEED_MODULES[_key], _published(_key, _SEED_MODULES[_key]).fn)


def is_event_fed(computation_key: str) -> bool:
    return computation_key.startswith("published:") or computation_key in PUBLISHED_SEED_KEYS


def is_manual(computation_key: str) -> bool:
    return computation_key == "manual.input"
