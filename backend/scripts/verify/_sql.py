"""Verification helper: run one read-only SQL statement on the platform role and print the rows as JSON.

    python scripts/verify/_sql.py "SELECT code, id FROM departments WHERE ..."   -> [{"code": "CSE", "id": "…"}, …]
    python scripts/verify/_sql.py --write "DELETE …; UPDATE …"                     -> fixture reset (one transaction)

Used by the PowerShell verification scripts instead of inline ``python -c`` programs (multi-line code with nested
quotes does not survive PowerShell 7's native argument passing on every platform).
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _bootstrap  # noqa: E402,F401
from sqlalchemy import text  # noqa: E402

from app.db.session import platform_engine  # noqa: E402


async def main(sql: str, write: bool) -> None:
    if write:
        async with platform_engine.begin() as conn:
            for stmt in (s.strip() for s in sql.split(";")):
                if stmt:
                    await conn.execute(text(stmt))
        print("[]")
    else:
        async with platform_engine.connect() as conn:
            rows = (await conn.execute(text(sql))).mappings().all()
        print(json.dumps([dict(r) for r in rows], default=str))
    await platform_engine.dispose()


if __name__ == "__main__":
    args = sys.argv[1:]
    write = "--write" in args
    args = [a for a in args if a != "--write"]
    asyncio.run(main(args[0], write))
