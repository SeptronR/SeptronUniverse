"""Verification helper: provide a demo login the phase 16-28 scripts expect but the seed never created.

    python scripts/verify/_ensure_demo_user.py grievance.off grievance_officer
    python scripts/verify/_ensure_demo_user.py staff.1 --staff hr_officer      # links an unused staff row
    python scripts/verify/_ensure_demo_user.py A24BTECHCSE001 --existing student_2   # password for a seeded login

Creates the demo-uni user with the role at institution scope (idempotent), sets a generated password and appends a
``| role | identifier | password |`` row to LOCAL_TEST_CREDENTIALS.md (git-ignored). Never prints the password.
"""

import asyncio
import secrets
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _bootstrap  # noqa: E402,F401
from sqlalchemy import text  # noqa: E402

from app.core.security import hash_password  # noqa: E402
from app.db.session import platform_engine  # noqa: E402


async def main(username: str, role: str, *, link_staff: bool, existing: bool) -> None:
    pwd = "Demo@" + secrets.token_hex(4)
    async with platform_engine.begin() as conn:
        inst = (await conn.execute(text("SELECT id FROM institutions WHERE slug = 'demo-uni'"))).scalar_one()
        uid = (
            await conn.execute(
                text("SELECT id FROM users WHERE institution_id = :i AND username = :u"), {"i": inst, "u": username}
            )
        ).scalar_one_or_none()
        if existing:
            await conn.execute(
                text("UPDATE users SET password_hash = :h, must_change_password = FALSE WHERE id = :id"),
                {"h": hash_password(pwd), "id": uid},
            )
        elif uid is None:
            uid = uuid.uuid4()
            await conn.execute(
                text(
                    "INSERT INTO users (id, institution_id, username, email, display_name, user_type, password_hash, "
                    "is_verified, must_change_password) VALUES (:id, :i, :u, :e, :d, 'staff', :h, TRUE, FALSE)"
                ),
                {"id": uid, "i": inst, "u": username, "e": f"{username}@demo-uni.septronuniverse.in", "d": username,
                 "h": hash_password(pwd)},
            )
            await conn.execute(
                text(
                    "INSERT INTO user_roles (institution_id, user_id, role_id, scope_type) SELECT :i, :u, id, "
                    "'institution' FROM roles WHERE institution_id = :i AND slug = :r AND deleted_at IS NULL"
                ),
                {"i": inst, "u": uid, "r": role},
            )
            if link_staff:
                await conn.execute(
                    text(
                        "UPDATE staff SET user_id = :u WHERE id = (SELECT id FROM staff WHERE institution_id = :i "
                        "AND user_id IS NULL AND deleted_at IS NULL ORDER BY employee_id LIMIT 1)"
                    ),
                    {"u": uid, "i": inst},
                )
        else:
            return  # already provisioned: its sheet row stands
    await platform_engine.dispose()
    sheet = Path(__file__).resolve().parents[3] / "LOCAL_TEST_CREDENTIALS.md"
    with sheet.open("a", encoding="utf-8") as f:
        f.write(f"| {role} | {username} | `{pwd}` |\n")


if __name__ == "__main__":
    a = sys.argv[1:]
    flags = {x for x in a if x.startswith("--")}
    pos = [x for x in a if not x.startswith("--")]
    asyncio.run(main(pos[0], pos[1], link_staff="--staff" in flags, existing="--existing" in flags))
