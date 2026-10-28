"""Lock-protected ``alembic upgrade head`` — Prompts/44 §44.6 docker & migrations 2.

Several backend replicas may start at once; only the holder of ``pg_advisory_lock(0x554E4956)`` ("UNIV") migrates, the
others wait and then report the head. Afterwards the schema-drift check runs (warning only) and the platform catalogue
refresh (``seed_platform.py`` — idempotent permissions / features / plans) keeps the registries in sync.

    python scripts/migrate_with_lock.py [--no-refresh]
"""

import argparse
import asyncio
import subprocess
import sys
import time

import _bootstrap  # noqa: F401
from sqlalchemy import text

LOCK = 0x554E4956


async def _version(conn: object) -> str | None:
    try:
        return (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar_one_or_none()  # type: ignore[attr-defined, no-any-return]
    except Exception:  # noqa: BLE001 - fresh database: no alembic_version yet
        return None


async def migrate() -> int:
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.core.config import settings

    engine = create_async_engine(settings.PLATFORM_DATABASE_URL or settings.DATABASE_URL, isolation_level="AUTOCOMMIT")
    t0 = time.monotonic()
    async with engine.connect() as conn:
        print("-> waiting for the migration lock")  # noqa: T201
        await conn.execute(text("SELECT pg_advisory_lock(:k)"), {"k": LOCK})
        try:
            before = await _version(conn)
            proc = await asyncio.create_subprocess_exec(sys.executable, "-m", "alembic", "upgrade", "head")
            rc = await proc.wait()
            if rc != 0:
                print("!! alembic upgrade failed")  # noqa: T201
                return rc
            after = await _version(conn)
            print(f"-> database at {after} (was {before}) in {time.monotonic() - t0:.1f}s")  # noqa: T201
        finally:
            await conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK})
    await engine.dispose()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-refresh", action="store_true")
    args = ap.parse_args()
    rc = asyncio.run(migrate())
    if rc != 0:
        return rc
    if subprocess.call([sys.executable, "scripts/check_schema_drift.py"]) != 0:  # noqa: S603
        print("!! schema drift reported (warning — investigate before the next release)")  # noqa: T201
    if not args.no_refresh:
        subprocess.call([sys.executable, "scripts/seed_platform.py"])  # noqa: S603
    return 0


if __name__ == "__main__":
    sys.exit(main())
