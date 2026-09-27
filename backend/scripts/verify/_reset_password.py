"""Verification helper: restore a demo user's password from LOCAL_TEST_CREDENTIALS.md (fixture reset).

    python scripts/verify/_reset_password.py hr Demo@123456

Used by ``02_auth_rbac.ps1`` step 0 — its credential-sheet step (17) rotates ``hr``'s password and sets
``must_change_password``, so a second run could not sign in as ``hr`` otherwise.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _bootstrap  # noqa: E402,F401
from sqlalchemy import text  # noqa: E402

from app.core.security import hash_password  # noqa: E402
from app.db.session import platform_engine  # noqa: E402


async def main(username: str, password: str) -> None:
    async with platform_engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE users SET password_hash = :h, must_change_password = FALSE, "
                "preferences = COALESCE(preferences, '{}'::jsonb) - 'password_history' WHERE username = :u"
            ),
            {"h": hash_password(password), "u": username},
        )
    await platform_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2]))
