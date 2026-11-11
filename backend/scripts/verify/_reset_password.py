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


async def reset_all() -> None:
    """``--all``: restore every recorded demo password, clear login lockouts, and drop MFA enrolments the sheet holds
    no ``<role>_totp`` secret for (plus the super admin's), so ``Login-Mfa`` re-enrols them. ``run_all.py`` calls this
    before each API script: scripts rotate passwords / enrol MFA and would otherwise break the ones after them."""
    from app.db.session import redis_client

    sheet = Path(__file__).resolve().parents[3] / "LOCAL_TEST_CREDENTIALS.md"
    passwords: dict[str, str] = {}
    totp: set[str] = set()
    for line in sheet.read_text(encoding="utf-8").splitlines():
        c = [x.strip().strip("`") for x in line.split("|")]
        if len(c) < 5 or not c[2] or not c[3] or c[1] == "role" or c[1].startswith("-"):
            continue
        if c[1].endswith("_totp"):
            totp.add(c[2])
        else:
            passwords[c[2]] = c[3]  # last row wins, as in Get-DemoPassword
    async with platform_engine.begin() as conn:
        for username, password in passwords.items():
            await conn.execute(
                text(
                    "UPDATE users SET password_hash = :h, must_change_password = FALSE, "
                    "preferences = COALESCE(preferences, '{}'::jsonb) - 'password_history' WHERE username = :u"
                ),
                {"h": hash_password(password), "u": username},
            )
        # time-boxed demo accounts (auditor.tmp 7 d, examiner.ext 30 d) expire on the calendar: keep them usable
        await conn.execute(
            text("UPDATE users SET valid_to = NOW() + INTERVAL '7 days' WHERE valid_to < NOW() AND username = ANY(:u)"),
            {"u": list(passwords)},
        )
        await conn.execute(
            text(
                "UPDATE user_roles SET valid_to = NOW() + INTERVAL '7 days' WHERE valid_to < NOW() "
                "AND user_id IN (SELECT id FROM users WHERE username = ANY(:u))"
            ),
            {"u": list(passwords)},
        )
        # every demo enrolment is dropped: Login-Mfa re-enrols and records the new secret (a stored secret can go stale)
        stale = "SELECT id FROM users WHERE is_super_admin OR username = ANY(:t) OR NOT (username = ANY(:t))"
        await conn.execute(text(f"DELETE FROM mfa_secrets WHERE user_id IN ({stale})"), {"t": list(totp)})
        await conn.execute(
            text(f"UPDATE users SET mfa_enabled = FALSE WHERE id IN ({stale}) AND mfa_enabled"), {"t": list(totp)}
        )
    await platform_engine.dispose()
    async for key in redis_client.scan_iter("login_fail:*"):
        await redis_client.delete(key)
    print(f"restored {len(passwords)} demo passwords")


if __name__ == "__main__":
    asyncio.run(reset_all() if sys.argv[1:] == ["--all"] else main(sys.argv[1], sys.argv[2]))
