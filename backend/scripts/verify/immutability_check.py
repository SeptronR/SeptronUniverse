"""Immutability suite (database level) — Prompts/43 §43.6 ``immutability_check_service`` / §43.11 step 4.

* published result rows are protected by triggers (``trg_results_immutable`` / ``trg_term_results_immutable``) — an
  ``UPDATE`` of a protected column on a published row raises (probed inside a rolled-back transaction when a published
  row exists);
* ``audit_logs`` (every partition): the application role holds no ``UPDATE`` / ``DELETE`` / ``TRUNCATE`` and the hash-
  chain trigger is installed;
* ``issued_documents`` are never updated in place by the application role's code paths (revoke + reissue) — reported
  as a warning when the grant exists.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _bootstrap  # noqa: E402, F401
from sqlalchemy import text  # noqa: E402

TRIGGERS = {
    "student_course_results": "trg_results_immutable",
    "student_term_results": "trg_term_results_immutable",
    "audit_logs": "trg_audit_hash_chain",
}


async def main() -> int:
    from app.db.session import engine, platform_engine

    problems: list[str] = []
    warnings: list[str] = []
    async with platform_engine.connect() as pc:
        for table, trg in TRIGGERS.items():
            ok = (
                await pc.execute(
                    text(
                        "SELECT 1 FROM pg_trigger WHERE NOT tgisinternal AND tgrelid = CAST(:t AS regclass) AND tgname = :g"
                    ),
                    {"t": table, "g": trg},
                )
            ).first()
            if not ok:
                problems.append(f"trigger {trg} missing on {table}")
        parts = [
            r[0]
            for r in (
                await pc.execute(
                    text(
                        "SELECT 'audit_logs' UNION SELECT c.relname FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid "
                        "WHERE i.inhparent = 'audit_logs'::regclass"
                    )
                )
            ).all()
        ]
        app_role = (
            await pc.execute(text("SELECT split_part(split_part(:u, '://', 2), ':', 1)"), {"u": str(engine.url)})
        ).scalar_one()
        for p in parts:
            for priv in ("UPDATE", "DELETE", "TRUNCATE"):
                if (
                    await pc.execute(text("SELECT has_table_privilege(:r, :t, :p)"), {"r": app_role, "t": p, "p": priv})
                ).scalar_one():
                    problems.append(f"{app_role} holds {priv} on {p}")
        if (
            await pc.execute(text("SELECT has_table_privilege(:r, 'issued_documents', 'DELETE')"), {"r": app_role})
        ).scalar_one():
            warnings.append(f"{app_role} holds DELETE on issued_documents (code revokes + reissues; consider revoking)")
        published = (
            (
                await pc.execute(
                    text("SELECT id, institution_id FROM student_course_results WHERE is_published LIMIT 1")
                )
            ).first()
            if (
                await pc.execute(
                    text(
                        "SELECT 1 FROM information_schema.columns WHERE table_name = 'student_course_results' AND column_name = 'is_published'"
                    )
                )
            ).first()
            else None
        )
    if published:
        async with engine.connect() as conn:
            trans = await conn.begin()
            try:
                await conn.execute(text("SELECT set_config('app.institution_id', :i, true)"), {"i": str(published[1])})
                await conn.execute(
                    text("UPDATE student_course_results SET total_marks = coalesce(total_marks, 0) + 1 WHERE id = :i"),
                    {"i": published[0]},
                )
                problems.append("UPDATE of a published student_course_results row succeeded")
            except Exception:  # noqa: BLE001 - expected: trigger exception
                pass
            finally:
                await trans.rollback()
    print(
        f"immutability: {len(TRIGGERS)} triggers, {len(parts)} audit partitions checked, published probe={'yes' if published else 'no rows'}"
    )  # noqa: T201
    for w in warnings:
        print(f"  WARN {w}")  # noqa: T201
    for p in problems:
        print(f"  FAIL {p}")  # noqa: T201
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
