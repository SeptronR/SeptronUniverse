"""Isolation suite (database level) — Prompts/43 §43.6 ``visibility_check_service`` / §43.11 step 2.

1. Every table with an ``institution_id`` column has row-level security enabled (or is a reviewed platform table).
2. RLS raw check: on the **application role** connection, with ``app.institution_id`` pinned to tenant B (a fresh
   random id when only one tenant exists), every tenant table returns 0 rows belonging to any other tenant (shared
   platform rows — ``institution_id IS NULL`` templates, role templates — are visible by policy and not counted).
3. The application role cannot ``SET ROLE universe_platform`` and is not BYPASSRLS.

The API-level matrix (52 roles × module lists → ``meta.visibility``) is ``scripts/verify/visibility_matrix.json`` driven
by ``43_hardening.ps1``; this script needs only the database.
"""

import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _bootstrap  # noqa: E402, F401
from sqlalchemy import text  # noqa: E402

# tables with an institution_id that are platform-owned (read through the platform session) — reviewed
PLATFORM_TABLES = {
    "institutions",
    "platform_settings",
    "platform_announcements",
    "support_tickets",
    "pending_registrations",
    "demo_requests",
    "impersonation_logs",
    "read_only_modes",
    "background_jobs",
    "outbox_events",
    "domain_events",
    "device_tokens",
    "users",
    "user_sessions",
    "login_history",
    "idempotency_keys",
    "usage_records",
    "subscriptions",
}


async def main() -> int:
    from app.db.session import engine, platform_engine

    problems: list[str] = []
    async with platform_engine.connect() as pc:
        tables = [
            (r[0], bool(r[1]))
            for r in (
                await pc.execute(
                    text(
                        "SELECT c.relname, c.relrowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                        "JOIN information_schema.columns col ON col.table_name = c.relname AND col.table_schema = n.nspname "
                        "WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p') AND col.column_name = 'institution_id' "
                        "AND NOT c.relispartition ORDER BY 1"
                    )
                )
            ).all()
        ]
        tenants = [r[0] for r in (await pc.execute(text("SELECT id FROM institutions ORDER BY created_at"))).all()]
    no_rls = [t for t, rls in tables if not rls and t not in PLATFORM_TABLES]
    problems += [f"RLS disabled on tenant table {t}" for t in no_rls]
    target = tenants[1] if len(tenants) > 1 else uuid.uuid4()
    leaks = 0
    async with engine.connect() as conn:
        async with conn.begin():
            role = (
                await conn.execute(
                    text("SELECT current_user, (SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user)")
                )
            ).one()
        if role[1]:
            problems.append(f"application role {role[0]} has BYPASSRLS")
        for table, rls in tables:
            if not rls:
                continue
            async with conn.begin():
                await conn.execute(text("SELECT set_config('app.institution_id', :i, true)"), {"i": str(target)})
                n = (
                    await conn.execute(
                        text(
                            f'SELECT count(*) FROM "{table}" WHERE institution_id IS NOT NULL AND institution_id <> :i'
                        ),
                        {"i": target},
                    )  # noqa: S608
                ).scalar_one()
            if n:
                leaks += 1
                problems.append(f"RLS leak: {table} returned {n} foreign rows")
        try:
            async with conn.begin():
                await conn.execute(text("SET ROLE universe_platform"))
            problems.append("application role can SET ROLE universe_platform")
        except Exception:  # noqa: BLE001 - expected: permission denied
            pass
    print(
        f"isolation: {len(tables)} tenant tables, {sum(1 for _, r in tables if r)} with RLS, {leaks} leaks, tenants={len(tenants)}"
    )  # noqa: T201
    for p in problems:
        print(f"  FAIL {p}")  # noqa: T201
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
