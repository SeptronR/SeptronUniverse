"""Verification helper: delete fixture rows together with everything later phases hung off them.

    python scripts/verify/_purge.py student_program_enrollments "entry_type = 'exit_reentry' AND student_id IN (...)"

Older scripts reset their fixtures with plain DELETEs, but later phases add rows that reference those fixtures through
foreign keys without ``ON DELETE CASCADE`` (fee invoices for an enrolment, transport allocations for an invoice, …), so
the reset fails (QA-012). This walks ``pg_constraint`` from the target table: a referencing row is detached
(``SET NULL``) when its column is nullable, otherwise purged the same way, depth first; then the targets are deleted.
One transaction on the platform role. Prints ``{"deleted": n, "detached": m}``. Development / verification only.
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _bootstrap  # noqa: E402,F401
from sqlalchemy import text  # noqa: E402

from app.db.session import platform_engine  # noqa: E402

# single-column foreign keys pointing at a table, on regular / partitioned parents (not their partitions)
FKS = """
SELECT c.conrelid::regclass::text AS child, a.attname AS col, NOT a.attnotnull AS nullable, c.confdeltype AS del
FROM pg_constraint c
JOIN pg_class r ON r.oid = c.conrelid
JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
WHERE c.contype = 'f' AND c.confrelid = CAST(:t AS regclass) AND array_length(c.conkey, 1) = 1 AND NOT r.relispartition
"""


async def purge(conn, table: str, ids: list, stats: dict, depth: int = 0) -> None:  # noqa: ANN001
    if not ids or depth > 8:
        return
    for fk in (await conn.execute(text(FKS), {"t": table})).mappings().all():
        if fk["del"] in ("c", "n"):  # cascade / set null: the database handles the row itself
            if fk["del"] == "c":
                kids = (
                    await conn.execute(text(f'SELECT id FROM {fk["child"]} WHERE "{fk["col"]}" = ANY(:ids)'), {"ids": ids})
                ).scalars().all() if await _has_id(conn, fk["child"]) else []
                await purge(conn, fk["child"], list(kids), stats, depth + 1)
            continue
        if fk["nullable"]:
            r = await conn.execute(
                text(f'UPDATE {fk["child"]} SET "{fk["col"]}" = NULL WHERE "{fk["col"]}" = ANY(:ids)'), {"ids": ids}
            )
            stats["detached"] += r.rowcount or 0
        elif await _has_id(conn, fk["child"]):
            kids = (
                await conn.execute(text(f'SELECT id FROM {fk["child"]} WHERE "{fk["col"]}" = ANY(:ids)'), {"ids": ids})
            ).scalars().all()
            await purge(conn, fk["child"], list(kids), stats, depth + 1)
            await conn.execute(text(f'DELETE FROM {fk["child"]} WHERE "{fk["col"]}" = ANY(:ids)'), {"ids": ids})
        else:
            await conn.execute(text(f'DELETE FROM {fk["child"]} WHERE "{fk["col"]}" = ANY(:ids)'), {"ids": ids})
    r = await conn.execute(text(f"DELETE FROM {table} WHERE id = ANY(:ids)"), {"ids": ids})
    stats["deleted"] += r.rowcount or 0


async def _has_id(conn, table: str) -> bool:  # noqa: ANN001
    q = "SELECT 1 FROM pg_attribute WHERE attrelid = CAST(:t AS regclass) AND attname = 'id' AND NOT attisdropped"
    return (await conn.execute(text(q), {"t": table})).first() is not None


async def main(table: str, where: str) -> None:
    stats = {"deleted": 0, "detached": 0}
    async with platform_engine.begin() as conn:
        ids = (await conn.execute(text(f"SELECT id FROM {table} WHERE {where}"))).scalars().all()
        await purge(conn, table, list(ids), stats)
    await platform_engine.dispose()
    print(json.dumps(stats))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2]))
