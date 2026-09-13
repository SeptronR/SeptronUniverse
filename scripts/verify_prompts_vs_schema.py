"""Verify that every table named in the phase prompts' "Database tables" sections exists in Database_Schema.sql.

Usage:  python scripts/verify_prompts_vs_schema.py [Prompts/NN_*.md ...]
Exit 1 when a prompt references a table that the canonical schema does not define.
"""
from __future__ import annotations
import re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "Database_Schema.sql"
PROMPTS = ROOT / "Prompts"

TABLE_RE = re.compile(r"^CREATE TABLE (?:IF NOT EXISTS )?([a-z_]+)", re.M)
SECTION_RE = re.compile(r"^## \d\d\.1 Database tables\s*$(.*?)^## \d\d\.2", re.M | re.S)
IDENT_RE = re.compile(r"\b([a-z][a-z0-9_]{2,})\b")
IGNORE = {
    # prose words that look like identifiers
    "section", "sections", "and", "the", "exist", "expected", "delta", "migration", "none", "tables", "already", "created", "in",
    "phase", "verify", "they", "copy", "do", "not", "retype", "also", "helper", "functions", "rls", "block", "trigger", "seeds",
    "default", "partition", "plus", "all", "of", "table", "with", "from", "for", "as", "is", "are", "to", "a", "an", "or",
}


def schema_tables() -> set[str]:
    return set(TABLE_RE.findall(SCHEMA.read_text(encoding="utf-8")))


def prompt_tables(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    found: set[str] = set()
    for m in SECTION_RE.finditer(text):
        body = m.group(1)
        # identifiers inside backticks or comma lists; keep snake_case-looking names only
        for ident in IDENT_RE.findall(body):
            if "_" in ident and ident not in IGNORE:
                found.add(ident)
    return found


def main(argv: list[str]) -> int:
    tables = schema_tables()
    files = [Path(a) for a in argv] or sorted(PROMPTS.glob("[0-9][0-9]_Phase*.md"))
    bad = 0
    for f in files:
        refs = prompt_tables(f)
        # drop obvious non-table identifiers (functions, column-ish words)
        refs = {r for r in refs if not r.startswith(("trigger_", "attach_", "current_", "fk_", "ix_", "uq_"))}
        missing = sorted(r for r in refs if r not in tables)
        # tolerate names that are clearly columns/enums (contain 'status' or end with '_id') to reduce noise
        missing = [m for m in missing if not (m.endswith("_id") or "status" in m)]
        print(f"{f.name}: {len(refs)} refs, {len(missing)} missing")
        for m in missing:
            print(f"   MISSING: {m}"); bad += 1
    print(f"schema tables: {len(tables)}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
