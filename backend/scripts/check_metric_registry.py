"""Metric registry guard — Prompts/32 §32.11 step 2.

Every seeded ``metric_definitions.computation_key`` (the §36.5 rows in ``Database_Schema.sql`` plus
``app/enums/accreditation.py:METRIC_DEFINITIONS`` inserted by ``0032``) must have a function registered in
``app/core/metrics.py`` (per-module registrations under ``app/services/accreditation/metrics``); every
``depends_on`` key must be defined; every criterion ``metric_key`` in ``FRAMEWORK_TREES`` must be a defined key.

    python scripts/check_metric_registry.py      # exit 1 listing missing registrations
"""

import re
import sys

import _bootstrap  # noqa: F401


def seeded_sql_keys() -> dict[str, str]:
    """``key → computation_key`` of the §36.5 seed rows."""
    sql = _bootstrap.SCHEMA_SQL.read_text(encoding="utf-8")
    m = re.search(
        r"INSERT INTO metric_definitions \(key, name, unit, source_module, computation_key\) VALUES(.*?)ON CONFLICT",
        sql,
        re.S,
    )
    if not m:
        return {}
    return {
        k: ck for k, _n, _u, _m, ck in re.findall(r"\('([^']+)','([^']*)','([^']*)','([^']*)','([^']+)'\)", m.group(1))
    }


def main() -> int:
    from app.core.metrics import REGISTRY
    from app.enums.accreditation import FRAMEWORK_TREES, METRIC_DEFINITIONS
    from app.services.accreditation import metrics  # noqa: F401  (fills REGISTRY)

    seeded = seeded_sql_keys()
    defined = dict(seeded)
    defined.update({k: ck for k, _n, _u, _m, ck, _p, _d in METRIC_DEFINITIONS})
    missing = sorted(f"{k} → {ck}" for k, ck in defined.items() if ck not in REGISTRY)
    deps = sorted(
        f"{k} depends on undefined {d}" for k, *_r, dl in METRIC_DEFINITIONS for d in dl or [] if d not in defined
    )
    links = sorted(
        {
            f"{fw} {code} → {mk}"
            for fw, rows in FRAMEWORK_TREES.items()
            for code, _t, _mt, _ms, mk, _p in rows
            if mk and mk not in defined
        }
    )
    print(
        f"metric definitions: {len(defined)} ({len(seeded)} seeded by 0001, {len(METRIC_DEFINITIONS)} by 0032); registered functions: {len(REGISTRY)}"
    )  # noqa: T201
    problems = missing + deps + links
    for p in problems:
        print(f"  MISSING {p}")  # noqa: T201
    if problems:
        return 1
    print("0 missing")  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())
