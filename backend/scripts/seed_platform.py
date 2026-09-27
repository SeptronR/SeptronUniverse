"""Platform seeder (idempotent) — Prompts/00_PREREQUISITE_Project_Setup.md §3 tree and §8; Prompts/02 §02.2.

    python scripts/seed_platform.py            # permissions, role templates (+ grants), features, plans, packs, super admin
    python scripts/seed_platform.py --refresh  # same (alias used by docker-entrypoint / Phase 44)

The registry seeding itself lives in ``app/services/install_service.py`` so the Alembic revision ``0002``, this script
and ``POST /install`` write exactly the same rows:

* permissions: the 916 ``module:action`` rows of ``app/core/rbac/registry.py`` (= Database_Schema.sql §36.1);
* role templates (§36.2, ``institution_id IS NULL``) **with their default grants** from
  ``docs/Roles_and_Permissions.md`` §3 — grants are added, never removed;
* ``platform_features``: every key of ``docs/Feature_Flags.md`` ∪ the code registry;
* ``subscription_plans`` (§36.3) with ``enabled_features`` per tier (Feature_Flags §3);
* ``platform_settings.regulatory_packs``: the registered pack codes.

A super admin (``SUPERADMIN_EMAIL``) is created when none exists — the generated password is written to
``LOCAL_TEST_CREDENTIALS.md`` (git-ignored), never printed to CI logs.
"""

import argparse
import asyncio
import sys
from datetime import UTC, datetime

import _bootstrap  # noqa: F401
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


async def seed_super_admin(conn: AsyncConnection, reset: bool = False) -> str | None:
    """Create the super admin when none exists; ``--reset-super-admin`` re-issues the password of the existing one."""
    from app.core.config import settings
    from app.core.security import generate_temp_password, hash_password

    exists = (
        await conn.execute(
            text("SELECT id FROM users WHERE is_super_admin AND deleted_at IS NULL ORDER BY created_at LIMIT 1")
        )
    ).first()
    if exists and not reset:
        return None
    password = generate_temp_password(16)
    if exists:
        await conn.execute(
            text(
                "UPDATE users SET password_hash = :hash, must_change_password = FALSE, is_active = TRUE, "
                "password_changed_at = NOW(), updated_at = NOW() WHERE id = :id"
            ),
            {"hash": hash_password(password), "id": exists[0]},
        )
    else:
        await conn.execute(
            text(
                "INSERT INTO users (institution_id, username, email, password_hash, display_name, user_type, is_super_admin, "
                "is_verified, must_change_password) VALUES (NULL, 'superadmin', :email, :hash, 'Platform Super Admin', "
                "'platform', TRUE, TRUE, FALSE)"
            ),
            {"email": settings.SUPERADMIN_EMAIL, "hash": hash_password(password)},
        )
    creds = _bootstrap.REPO_ROOT / "LOCAL_TEST_CREDENTIALS.md"
    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    with creds.open("a", encoding="utf-8") as f:
        f.write(
            f"\n## Platform super admin (seed_platform.py, {stamp})\n\n| role | identifier | password |\n|---|---|---|\n"
        )
        f.write(f"| super_admin | superadmin | `{password}` |\n")
    return str(creds)


async def run(reset_super_admin: bool = False) -> int:
    from app.db.session import platform_engine
    from app.services.install_service import seed_registries

    async with platform_engine.begin() as conn:
        missing = (
            await conn.execute(
                text(
                    "SELECT string_agg(t, ', ') FROM unnest(ARRAY['permissions','roles','role_permissions','platform_features',"
                    "'subscription_plans','platform_settings','users']) t WHERE to_regclass(t) IS NULL"
                )
            )
        ).scalar_one()
        if missing:
            print(
                f"ERROR: tables missing ({missing}) - run 'alembic upgrade head' (Phase 01) or 'psql -f Database_Schema.sql' first"
            )
            return 1
        counts = await conn.run_sync(seed_registries)
        creds = await seed_super_admin(conn, reset=reset_super_admin)
        roles = (await conn.execute(text("SELECT count(*) FROM roles WHERE institution_id IS NULL"))).scalar_one()
        grants = (
            await conn.execute(
                text(
                    "SELECT count(*) FROM role_permissions rp JOIN roles r ON r.id = rp.role_id WHERE r.institution_id IS NULL"
                )
            )
        ).scalar_one()
    print(
        f"permissions: {counts['permissions']} · role templates: {roles} (+{counts['role_templates_created']} new, "
        f"{grants} grants, +{counts['role_template_grants_added']}) · platform_features: {counts['features']} upserted · "
        f"plans: {counts['plans']} ({counts['plan_tiers_updated']} tiers updated) · packs: {counts['packs']}"
    )
    if creds:
        print(f"super admin credentials written to {creds}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--refresh", action="store_true", help="alias; the seeder is always idempotent")
    ap.add_argument(
        "--reset-super-admin",
        action="store_true",
        help="re-issue the super admin password (development: the password is written to LOCAL_TEST_CREDENTIALS.md)",
    )
    args = ap.parse_args()
    return asyncio.run(run(args.reset_super_admin))


if __name__ == "__main__":
    sys.exit(main())
