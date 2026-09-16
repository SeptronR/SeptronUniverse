"""Split ``Database_Schema.sql`` into executable statements — Prompts/01 §01.2.

The canonical DDL is applied verbatim by revision ``0001`` (schema-first, ADR 0001). A naive ``split(";")`` breaks on
the PL/pgSQL bodies (``$$ … $$`` / ``$tag$ … $tag$``), on ``DO $$ … END $$;`` blocks and on semicolons inside string
literals, so this module walks the file with a small state machine:

* ``--`` line comments are dropped (outside strings / dollar quotes);
* ``'…'`` strings (``''`` escapes, backslashes are literal — ``standard_conforming_strings``) and ``"…"`` identifiers
  are copied verbatim;
* dollar-quoted blocks are tracked by tag so nested semicolons never split a statement;
* ``;`` at depth 0 terminates a statement; empty statements are skipped.

``find_schema_sql()`` resolves the file for every runtime: the repo checkout (``<root>/Database_Schema.sql``), a copy
next to ``backend/`` (Docker images / compose mount ``/app/Database_Schema.sql``) or ``SCHEMA_SQL_PATH``.
"""

import os
import re
from collections.abc import Iterator
from pathlib import Path

_DOLLAR_TAG = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*\$|\$\$")


def find_schema_sql(explicit: str | os.PathLike[str] | None = None) -> Path:
    """Locate ``Database_Schema.sql`` (explicit path → ``SCHEMA_SQL_PATH`` → repo root → backend/ → cwd)."""
    here = Path(__file__).resolve()
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    if os.environ.get("SCHEMA_SQL_PATH"):
        candidates.append(Path(os.environ["SCHEMA_SQL_PATH"]))
    candidates += [
        here.parents[2] / "Database_Schema.sql",  # <repo>/Database_Schema.sql  (alembic/ → backend/ → repo)
        here.parents[1] / "Database_Schema.sql",  # <backend>/Database_Schema.sql (container copy / mount)
        Path.cwd() / "Database_Schema.sql",
        Path.cwd().parent / "Database_Schema.sql",
    ]
    for c in candidates:
        if c.is_file():
            return c
    raise FileNotFoundError("Database_Schema.sql not found - set SCHEMA_SQL_PATH or run from the repository checkout")


def split_statements(sql: str) -> Iterator[str]:
    """Yield the statements of ``sql`` without their trailing ``;`` and without ``--`` comments."""
    buf: list[str] = []
    i, n = 0, len(sql)
    in_single = in_double = False
    dollar_tag: str | None = None
    while i < n:
        ch = sql[i]
        if dollar_tag is not None:
            if sql.startswith(dollar_tag, i):
                buf.append(dollar_tag)
                i += len(dollar_tag)
                dollar_tag = None
                continue
            buf.append(ch)
            i += 1
            continue
        if in_single:
            buf.append(ch)
            if ch == "'":
                if i + 1 < n and sql[i + 1] == "'":  # escaped quote ''
                    buf.append("'")
                    i += 2
                    continue
                in_single = False
            i += 1
            continue
        if in_double:
            buf.append(ch)
            if ch == '"':
                in_double = False
            i += 1
            continue
        # --- outside any quoting ---
        if ch == "-" and sql.startswith("--", i):
            j = sql.find("\n", i)
            i = n if j == -1 else j  # keep the newline as whitespace
            continue
        if ch == "/" and sql.startswith("/*", i):
            j = sql.find("*/", i + 2)
            i = n if j == -1 else j + 2
            continue
        if ch == "'":
            in_single = True
            buf.append(ch)
            i += 1
            continue
        if ch == '"':
            in_double = True
            buf.append(ch)
            i += 1
            continue
        if ch == "$":
            m = _DOLLAR_TAG.match(sql, i)
            if m:
                dollar_tag = m.group(0)
                buf.append(dollar_tag)
                i += len(dollar_tag)
                continue
        if ch == ";":
            stmt = "".join(buf).strip()
            if stmt:
                yield stmt
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        yield tail


def load_statements(path: str | os.PathLike[str] | None = None) -> list[str]:
    """Read the schema file (or the resolved canonical one) and return its statements in order."""
    target = find_schema_sql(path)
    return list(split_statements(target.read_text(encoding="utf-8")))


if __name__ == "__main__":  # quick self-check: python alembic/sql_loader.py
    stmts = load_statements()
    kinds: dict[str, int] = {}
    for s in stmts:
        kinds[" ".join(s.split()[:2]).upper()] = kinds.get(" ".join(s.split()[:2]).upper(), 0) + 1
    print(f"{len(stmts)} statements")  # noqa: T201
    for k, v in sorted(kinds.items(), key=lambda kv: -kv[1]):
        print(f"  {v:4d}  {k}")  # noqa: T201
