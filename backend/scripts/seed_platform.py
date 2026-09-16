"""Platform seeder (idempotent) — Prompts/00_PREREQUISITE_Project_Setup.md §3 tree and §8.

    python scripts/seed_platform.py            # permissions, role templates, features, plans, packs, super admin
    python scripts/seed_platform.py --refresh  # same (alias used by docker-entrypoint / Phase 44)

* permissions and subscription plans: executes the canonical ``INSERT ... ON CONFLICT DO NOTHING`` statements of
  ``Database_Schema.sql`` §36.1 / §36.3 (never retyped here);
* role templates (§36.2, ``institution_id IS NULL`` so ON CONFLICT cannot dedupe them): inserted when missing;
* ``platform_features``: every key of ``docs/Feature_Flags.md`` (group, default, tier, depends_on, is_core) merged with
  the code registry; plan ``enabled_features`` are derived from the tiers (Feature_Flags §3);
* ``platform_settings.regulatory_packs``: the registered pack codes;
* a super admin (``SUPERADMIN_EMAIL``) is created when none exists — the generated password is written to
  ``LOCAL_TEST_CREDENTIALS.md`` (git-ignored), never printed to CI logs.
"""

import argparse
import asyncio
import json
import re
import secrets
import sys
from datetime import UTC, datetime
from typing import Any

import _bootstrap  # noqa: F401
from feature_doc import load_doc_features
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

TIER_ORDER = ["starter", "standard", "professional", "university"]
ROLE_TUPLE_RE = re.compile(r"\(NULL,\s*'([^']+)',\s*'([a-z_]+)',\s*(TRUE|FALSE),\s*'([a-z_]+)',\s*'([a-z_]+)'\)")


def section(sql: str, marker: str, next_marker: str) -> str:
    start = sql.index(marker)
    end = sql.index(next_marker, start)
    return sql[start:end]


def statements(block: str) -> list[str]:
    out = []
    for stmt in block.split(";\n"):
        body = "\n".join(line for line in stmt.splitlines() if not line.strip().startswith("--")).strip()
        if body:
            out.append(body)
    return out


async def seed_permissions_and_plans(conn: AsyncConnection, sql: str) -> tuple[int, int]:
    perms_block = section(sql, "-- 36.1", "-- 36.2")
    plans_block = section(sql, "-- 36.3", "-- 36.4")
    for stmt in statements(perms_block) + statements(plans_block):
        await conn.exec_driver_sql(stmt)  # raw: the canonical seed statements are not bind-parameterised
    perms = (await conn.execute(text("SELECT count(*) FROM permissions"))).scalar_one()
    plans = (await conn.execute(text("SELECT count(*) FROM subscription_plans"))).scalar_one()
    return int(perms), int(plans)


async def seed_role_templates(conn: AsyncConnection, sql: str) -> int:
    block = section(sql, "-- 36.2", "-- 36.3")
    created = 0
    for name, slug, is_system, scope, portal in ROLE_TUPLE_RE.findall(block):
        exists = (
            await conn.execute(
                text("SELECT 1 FROM roles WHERE institution_id IS NULL AND slug = :slug"), {"slug": slug}
            )
        ).first()
        if exists:
            continue
        await conn.execute(
            text(
                "INSERT INTO roles (institution_id, name, slug, is_system, default_scope_type, portal) "
                "VALUES (NULL, :name, :slug, :is_system, :scope, :portal)"
            ),
            {"name": name, "slug": slug, "is_system": is_system == "TRUE", "scope": scope, "portal": portal},
        )
        created += 1
    return created


async def seed_features(conn: AsyncConnection) -> tuple[int, int]:
    import app.features  # noqa: F401
    from app.core.features import FEATURE_REGISTRY

    doc = load_doc_features()
    upserted = 0
    for key, d in sorted(doc.items()):
        reg = FEATURE_REGISTRY.get(key)
        params: dict[str, Any] = {
            "key": key,
            "group_name": (reg.group if reg else d.group)[:40],
            "name": (reg.name if reg else d.name)[:120],
            "description": (reg.description or d.description) if reg else d.description,
            "default_enabled": d.default_enabled,
            "min_plan_tier": d.min_plan_tier,
            "depends_on": json.dumps(list(d.depends_on)),
            "is_core": key.startswith("core."),
        }
        await conn.execute(
            text(
                "INSERT INTO platform_features (key, group_name, name, description, default_enabled, min_plan_tier, depends_on, is_core) "
                "VALUES (:key, :group_name, :name, :description, :default_enabled, :min_plan_tier, CAST(:depends_on AS jsonb), :is_core) "
                "ON CONFLICT (key) DO UPDATE SET group_name = EXCLUDED.group_name, name = EXCLUDED.name, "
                "description = EXCLUDED.description, default_enabled = EXCLUDED.default_enabled, "
                "min_plan_tier = EXCLUDED.min_plan_tier, depends_on = EXCLUDED.depends_on, is_core = EXCLUDED.is_core, "
                "updated_at = NOW()"
            ),
            params,
        )
        upserted += 1
    # Plan defaults: a tier includes every key at or below it whose default is on (Feature_Flags.md §3)
    plans_updated = 0
    for i, tier in enumerate(TIER_ORDER):
        enabled = sorted(k for k, d in doc.items() if d.default_enabled and TIER_ORDER.index(d.min_plan_tier) <= i)
        res = await conn.execute(
            text(
                "UPDATE subscription_plans SET enabled_features = CAST(:f AS jsonb), updated_at = NOW() WHERE tier = :tier"
            ),
            {"f": json.dumps(enabled), "tier": tier},
        )
        plans_updated += res.rowcount or 0
    return upserted, plans_updated


async def seed_packs(conn: AsyncConnection) -> list[str]:
    from app.core.packs import pack_codes

    codes = pack_codes()
    await conn.execute(
        text(
            "INSERT INTO platform_settings (key, value) VALUES ('regulatory_packs', CAST(:v AS jsonb)) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()"
        ),
        {"v": json.dumps(codes)},
    )
    return codes


async def seed_super_admin(conn: AsyncConnection) -> str | None:
    from app.core.config import settings
    from app.core.security import hash_password

    exists = (
        await conn.execute(text("SELECT 1 FROM users WHERE is_super_admin AND deleted_at IS NULL LIMIT 1"))
    ).first()
    if exists:
        return None
    password = secrets.token_urlsafe(12)
    await conn.execute(
        text(
            "INSERT INTO users (institution_id, username, email, password_hash, display_name, user_type, is_super_admin, "
            "is_verified, must_change_password) VALUES (NULL, 'superadmin', :email, :hash, 'Platform Super Admin', "
            "'platform', TRUE, TRUE, TRUE)"
        ),
        {"email": settings.SUPERADMIN_EMAIL, "hash": hash_password(password)},
    )
    creds = _bootstrap.REPO_ROOT / "LOCAL_TEST_CREDENTIALS.md"
    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    with creds.open("a", encoding="utf-8") as f:
        f.write(f"\n## Platform super admin (seed_platform.py, {stamp})\n\n| identifier | password |\n|---|---|\n")
        f.write(f"| superadmin / {settings.SUPERADMIN_EMAIL} | `{password}` |\n")
    return str(creds)


async def run() -> int:
    from app.db.session import platform_engine

    sql = _bootstrap.SCHEMA_SQL.read_text(encoding="utf-8")
    async with platform_engine.begin() as conn:
        missing = (
            await conn.execute(
                text(
                    "SELECT string_agg(t, ', ') FROM unnest(ARRAY['permissions','roles','platform_features','subscription_plans','platform_settings','users']) t "
                    "WHERE to_regclass(t) IS NULL"
                )
            )
        ).scalar_one()
        if missing:
            print(
                f"ERROR: tables missing ({missing}) - run 'alembic upgrade head' (Phase 01) or 'psql -f Database_Schema.sql' first"
            )
            return 1
        perms, plans = await seed_permissions_and_plans(conn, sql)
        roles = await seed_role_templates(conn, sql)
        features, plans_updated = await seed_features(conn)
        packs = await seed_packs(conn)
        creds = await seed_super_admin(conn)
    print(
        f"permissions: {perms} rows · role templates: +{roles} · platform_features: {features} upserted · plans: {plans} ({plans_updated} tiers updated) · packs: {packs}"
    )
    if creds:
        print(f"super admin created - credentials written to {creds}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--refresh", action="store_true", help="alias; the seeder is always idempotent")
    ap.parse_args()
    return asyncio.run(run())


if __name__ == "__main__":
    sys.exit(main())
