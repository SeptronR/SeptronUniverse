"""Mint a development access token — Prompts/01 §01.11 step 7 (until Phase 02 ships ``POST /auth/login``).

    python scripts/dev_token.py                       # the platform super admin (seed_platform.py)
    python scripts/dev_token.py --user superadmin     # by username or email
    python scripts/dev_token.py --minutes 120         # longer lifetime for a manual session

Prints the bearer token only (pipe it: ``$token = python scripts/dev_token.py``). Refuses to run when
``APP_ENV=production`` — the token is signed with the live ``SECRET_KEY`` and carries the user's real permissions.
"""

import argparse
import asyncio
import sys

import _bootstrap  # noqa: F401
from sqlalchemy import or_, select


async def mint(identifier: str | None, minutes: int) -> str:
    from app.core.config import settings
    from app.core.security import create_access_token
    from app.db.session import PlatformSessionLocal
    from app.models.platform import User

    if settings.APP_ENV == "production":
        raise SystemExit("refusing to mint a dev token in production")
    async with PlatformSessionLocal() as db:
        q = select(User).where(User.deleted_at.is_(None), User.is_active.is_(True))
        if identifier:
            q = q.where(or_(User.username == identifier, User.email == identifier))
        else:
            q = q.where(User.is_super_admin.is_(True))
        user = (await db.execute(q.order_by(User.created_at).limit(1))).scalar_one_or_none()
    if user is None:
        raise SystemExit(f"user not found: {identifier or '(super admin)'} - run scripts/seed_platform.py first")
    settings.ACCESS_TOKEN_EXPIRE_MINUTES = minutes
    return create_access_token(user.id, user.institution_id, user.is_super_admin)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--user", help="username or email (default: the super admin)")
    ap.add_argument("--minutes", type=int, default=60, help="token lifetime (default 60)")
    args = ap.parse_args()
    print(asyncio.run(mint(args.user, args.minutes)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
