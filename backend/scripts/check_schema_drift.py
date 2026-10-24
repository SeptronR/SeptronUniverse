"""Schema drift guard — Prompts/00_PREREQUISITE_Project_Setup.md §3.23.

Parses ``Database_Schema.sql`` (``CREATE TABLE name (...)`` blocks → table → column names) and compares it with
``Base.metadata`` (tables and columns present in the models).

    python scripts/check_schema_drift.py              # every modelled table must match the SQL
    python scripts/check_schema_drift.py --phase 01   # only the tables listed in scripts/phase_manifest.py["01"]
    python scripts/check_schema_drift.py --strict     # additionally: every SQL table must be modelled (Phase 43+)

Exit 1 with a readable diff: ``missing in models`` (only with --phase/--strict), ``extra in models``, ``column mismatch``.
"""

import argparse
import re
import sys
from pathlib import Path

import _bootstrap  # noqa: F401
from phase_manifest import VIEWS, tables_for

# whole-word match: a column named ``checked_at`` must not be mistaken for a CHECK constraint
CONSTRAINT_RE = re.compile(r"^(PRIMARY\s+KEY|UNIQUE|CONSTRAINT|FOREIGN\s+KEY|CHECK|EXCLUDE|LIKE)\b", re.IGNORECASE)


def strip_comments(sql: str) -> str:
    out: list[str] = []
    in_str = False
    i = 0
    while i < len(sql):
        ch = sql[i]
        if ch == "'" and not in_str:
            in_str = True
        elif ch == "'" and in_str:
            in_str = False
        elif not in_str and sql.startswith("--", i):
            j = sql.find("\n", i)
            i = len(sql) if j == -1 else j
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def split_top_level(body: str) -> list[str]:
    parts, depth, buf, quoted = [], 0, [], False
    for ch in body:
        if ch == "'":
            quoted = not quoted  # string literals (JSONB defaults) may hold commas
        if quoted:
            buf.append(ch)
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    return parts


def parse_schema(path: Path) -> dict[str, list[str]]:
    sql = strip_comments(path.read_text(encoding="utf-8"))
    tables: dict[str, list[str]] = {}
    for m in re.finditer(
        r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?\"?([A-Za-z_][A-Za-z0-9_]*)\"?\s*(\(|PARTITION\s+OF)", sql
    ):
        name = m.group(1)
        if m.group(2).upper().startswith("PARTITION"):
            tables.setdefault(name, [])  # partition child: no own columns
            continue
        start = m.end()
        depth, i = 1, start
        while i < len(sql) and depth:
            if sql[i] == "(":
                depth += 1
            elif sql[i] == ")":
                depth -= 1
            i += 1
        body = sql[start : i - 1]
        cols: list[str] = []
        for item in split_top_level(body):
            if not item or CONSTRAINT_RE.match(item):
                continue
            cols.append(item.split()[0].strip('"'))
        tables[name] = cols
    return tables


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--phase", help="compare only the tables of this phase (scripts/phase_manifest.py)")
    ap.add_argument("--strict", action="store_true", help="every SQL table must be modelled")
    ap.add_argument("--schema", default=str(_bootstrap.SCHEMA_SQL), help="path to Database_Schema.sql")
    args = ap.parse_args()

    schema_path = Path(args.schema)
    if not schema_path.exists():
        print(f"ERROR: {schema_path} not found")
        return 1
    sql_tables = parse_schema(schema_path)

    import app.models  # noqa: F401
    from app.db.session import Base

    model_tables = {
        name: [c.name for c in table.columns]
        for name, table in Base.metadata.tables.items()
        if not table.info.get("is_view") and name not in VIEWS
    }

    errors: list[str] = []
    partition_children = {n for n, cols in sql_tables.items() if not cols and n.endswith("_default")}

    scope = set(model_tables)
    if args.phase:
        wanted = set(tables_for(args.phase))
        for t in sorted(wanted - set(model_tables)):
            errors.append(f"missing in models: {t}")
        scope = wanted & set(model_tables)
    if args.strict:
        for t in sorted(set(sql_tables) - partition_children - set(model_tables)):
            errors.append(f"missing in models: {t}")

    for t in sorted(scope):
        if t not in sql_tables:
            errors.append(f"extra in models: {t} (not in Database_Schema.sql)")
            continue
        sql_cols, model_cols = set(sql_tables[t]), set(model_tables[t])
        if sql_cols != model_cols:
            missing = sorted(sql_cols - model_cols)
            extra = sorted(model_cols - sql_cols)
            detail = []
            if missing:
                detail.append(f"missing in model: {', '.join(missing)}")
            if extra:
                detail.append(f"extra in model: {', '.join(extra)}")
            errors.append(f"column mismatch: {t} -> " + "; ".join(detail))

    unmodelled = len(set(sql_tables) - partition_children - set(model_tables))
    print(
        f"schema drift check: {len(sql_tables) - len(partition_children)} SQL tables (+{len(partition_children)} partition defaults), "
        f"{len(model_tables)} modelled, {len(scope)} compared, {unmodelled} not yet modelled"
    )
    if errors:
        print("DRIFT DETECTED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("OK: 0 diffs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
