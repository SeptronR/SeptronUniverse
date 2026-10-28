"""Shared helpers for the ops scripts (Prompts/44 §44.6 ops scripts) — run inside the backend container:

    python scripts/ops/<script>.py --institution demo-uni …

Each script acts as the institution's first ``institution_admin`` (tenant scripts) or as a platform system principal,
writes an audit row through the services it calls, and prints a JSON result (the ``ops.script_run`` job stores it).
"""

import asyncio
import json
import sys
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _bootstrap  # noqa: E402, F401


async def tenant_admin(db: Any, slug: str) -> tuple[uuid.UUID, Any]:
    from sqlalchemy import text

    from app.db.session import bind_tenant, set_tenant
    from app.services.auth_service import load_principal

    iid = (
        await db.execute(text("SELECT id FROM institutions WHERE slug = :s AND deleted_at IS NULL"), {"s": slug})
    ).scalar_one()
    uid = (
        await db.execute(
            text(
                "SELECT u.id FROM users u JOIN user_roles ur ON ur.user_id = u.id JOIN roles r ON r.id = ur.role_id "
                "WHERE u.institution_id = :i AND r.slug = 'institution_admin' AND u.is_active AND u.deleted_at IS NULL "
                "ORDER BY u.created_at LIMIT 1"
            ),
            {"i": iid},
        )
    ).scalar_one()
    bind_tenant(db, iid)
    await set_tenant(db, iid)
    return iid, await load_principal(db, uid)


def run(fn: Callable[[Any], Awaitable[dict[str, Any]]], platform: bool = False) -> None:
    async def main() -> None:
        from app.db.session import PlatformSessionLocal, SessionLocal

        maker = PlatformSessionLocal if platform else SessionLocal
        async with maker() as db:
            try:
                out = await fn(db)
                await db.commit()
            except Exception:
                await db.rollback()
                raise
        print(json.dumps(out, default=str, indent=1))  # noqa: T201

    asyncio.run(main())
