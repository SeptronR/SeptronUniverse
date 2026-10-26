"""Accreditation catalogue seed — the complete ``framework_criteria`` trees and the ``metric_definitions`` beyond the
§36.5 seed (revision ``0032``; the demo seeder re-asserts it on databases migrated before 0032)."""

import json
from typing import Any

from sqlalchemy import text

from app.enums.accreditation import FRAMEWORK_TREES, METRIC_DEFINITIONS, parent_code


def seed_accreditation_catalogue(conn: Any) -> tuple[int, int]:
    """Criteria trees + metric definitions (idempotent) on a synchronous connection."""
    c = conn
    defs = 0
    for key, name, unit, module, ck, params, deps in METRIC_DEFINITIONS:
        res = c.execute(
            text(
                "INSERT INTO metric_definitions (key, name, unit, source_module, computation_key, params_schema, is_derived, depends_on) "
                "VALUES (:k, :n, :u, :m, :ck, CAST(:ps AS JSONB), :d, CAST(:dep AS JSONB)) "
                "ON CONFLICT (key) DO UPDATE SET computation_key = EXCLUDED.computation_key, params_schema = EXCLUDED.params_schema, "
                "is_derived = EXCLUDED.is_derived, depends_on = EXCLUDED.depends_on"
            ),
            {
                "k": key,
                "n": name,
                "u": unit,
                "m": module,
                "ck": ck,
                "ps": json.dumps(params) if params else None,
                "d": bool(deps),
                "dep": json.dumps(deps) if deps else None,
            },
        )
        defs += res.rowcount or 0
    crits = 0
    for fw_code, rows in FRAMEWORK_TREES.items():
        fid = c.execute(text("SELECT id FROM accreditation_frameworks WHERE code = :c"), {"c": fw_code}).scalar()
        if fid is None:
            continue
        for seq, (code, title, mtype, max_score, metric_key, period) in enumerate(
            sorted(rows, key=lambda r: (r[0].count("."), r[0])), start=1
        ):
            parent = parent_code(code)
            res = c.execute(
                text(
                    "INSERT INTO framework_criteria (framework_id, code, parent_id, title, metric_type, max_score, period_type, metric_key, sequence) "
                    "VALUES (:f, :code, (SELECT id FROM framework_criteria WHERE framework_id = :f AND code = :parent), :t, :mt, :ms, :pt, :mk, :seq) "
                    "ON CONFLICT (framework_id, code) DO UPDATE SET metric_key = COALESCE(EXCLUDED.metric_key, framework_criteria.metric_key), "
                    "parent_id = COALESCE(EXCLUDED.parent_id, framework_criteria.parent_id), period_type = EXCLUDED.period_type"
                ),
                {
                    "f": fid,
                    "code": code,
                    "parent": parent,
                    "t": title,
                    "mt": mtype,
                    "ms": max_score,
                    "pt": period,
                    "mk": metric_key,
                    "seq": seq,
                },
            )
            crits += res.rowcount or 0
    return defs, crits
