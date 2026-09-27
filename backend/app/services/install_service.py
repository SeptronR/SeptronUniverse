"""Platform bootstrap — Prompts/02 §02.2 (data-only seed) and §02.6 ``install_service`` (``POST /install``).

The seeding functions take a **synchronous** SQLAlchemy connection so the same code runs inside the Alembic
revision ``0002_phase02_auth_seed`` (sync context), from ``scripts/seed_platform.py`` (``AsyncConnection.run_sync``)
and from the ``/install`` endpoint. Everything is idempotent (``ON CONFLICT DO NOTHING / DO UPDATE``):

1. ``seed_permissions`` — the catalogue of ``app/core/rbac/registry.py`` (mirrors Database_Schema.sql §36.1);
2. ``seed_role_templates`` — the 51 templates (``institution_id IS NULL``) and their ``role_permissions`` rows from
   ``ROLE_TEMPLATES`` (grants are added, never removed — an operator's manual change to a template survives);
3. ``seed_features`` — ``platform_features`` from ``FEATURE_REGISTRY`` ∪ ``docs/Feature_Flags.md`` (doc wins for
   defaults/tier of keys no module has registered yet; both sources agree for registered keys — CI guard);
4. ``seed_plans`` — the four §36.3 plans and their ``enabled_features`` per tier (Feature_Flags §3);
5. ``seed_packs`` — ``platform_settings['regulatory_packs']``;
6. Phase 03 templates — ``seed_phase03_platform`` (``app/services/institution_defaults.py``).

Business rules of ``InstallService`` (rule 1 of the prompt): ``POST /install`` is guarded by ``INSTALL_SECRET_KEY``,
runs once (``platform_settings['installed']`` → ``409 CONFLICT`` afterwards), seeds the registries, creates the
super admin with ``must_change_password`` — an **existing** super admin is never touched, so the install key can
never reset live platform credentials — and records the install stamp.
"""

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import log_audit
from app.core.config import settings
from app.core.errors import APIError, ErrorCode
from app.core.feature_doc import load_doc_features
from app.core.rbac.registry import PERMISSIONS, ROLE_META, ROLE_TEMPLATES, template_permissions
from app.core.security import check_password_policy, hash_password

TIER_ORDER = ["starter", "standard", "professional", "university"]
PLANS: tuple[tuple[str, str, str, int, int, int, int], ...] = (  # §36.3 (code, name, tier, students, staff, gb, sms)
    ("starter", "Starter", "starter", 2000, 200, 20, 5000),
    ("standard", "Standard", "standard", 10000, 1000, 100, 25000),
    ("professional", "Professional", "professional", 50000, 5000, 500, 100000),
    ("university", "University", "university", 200000, 20000, 2000, 500000),
)


# ---- registries (sync connection) ------------------------------------------------------------------------------
def seed_permissions(conn: Connection) -> int:
    rows = [{"m": k.split(":", 1)[0], "a": k.split(":", 1)[1], "d": d} for k, d in PERMISSIONS.items()]
    conn.execute(
        text("INSERT INTO permissions (module, action, description) VALUES (:m, :a, :d) ON CONFLICT DO NOTHING"), rows
    )
    return int(conn.execute(text("SELECT count(*) FROM permissions")).scalar_one())


def seed_role_templates(conn: Connection) -> tuple[int, int]:
    """Insert missing templates and their default grants; returns (roles created, grants added)."""
    created = 0
    for meta in ROLE_META:
        row = conn.execute(
            text("SELECT id FROM roles WHERE institution_id IS NULL AND slug = :slug"), {"slug": meta.slug}
        ).first()
        if row is None:
            conn.execute(
                text(
                    "INSERT INTO roles (institution_id, name, slug, is_system, default_scope_type, portal) "
                    "VALUES (NULL, :name, :slug, :is_system, :scope, :portal)"
                ),
                {
                    "name": meta.name,
                    "slug": meta.slug,
                    "is_system": meta.is_system,
                    "scope": meta.default_scope_type,
                    "portal": meta.portal,
                },
            )
            created += 1
    perm_ids = {f"{m}:{a}": pid for pid, m, a in conn.execute(text("SELECT id, module, action FROM permissions")).all()}
    role_ids = {
        slug: rid for rid, slug in conn.execute(text("SELECT id, slug FROM roles WHERE institution_id IS NULL")).all()
    }
    added = 0
    for slug in ROLE_TEMPLATES:
        if "*:*" in ROLE_TEMPLATES[slug]:
            continue  # super admin: the user flag grants everything; no 916 rows for a label role
        rid = role_ids.get(slug)
        if rid is None:
            continue
        existing = {
            pid
            for (pid,) in conn.execute(
                text("SELECT permission_id FROM role_permissions WHERE role_id = :r"), {"r": rid}
            )
        }
        missing = [perm_ids[k] for k in template_permissions(slug) if k in perm_ids and perm_ids[k] not in existing]
        if missing:
            conn.execute(
                text("INSERT INTO role_permissions (role_id, permission_id) VALUES (:r, :p) ON CONFLICT DO NOTHING"),
                [{"r": rid, "p": pid} for pid in missing],
            )
            added += len(missing)
    return created, added


def _feature_rows() -> list[dict[str, Any]]:
    import app.features  # noqa: F401  (complete registry)
    from app.core.features import FEATURE_REGISTRY

    doc = load_doc_features()
    keys = sorted(set(FEATURE_REGISTRY) | set(doc))
    rows: list[dict[str, Any]] = []
    for key in keys:
        reg = FEATURE_REGISTRY.get(key)
        d = doc.get(key)
        rows.append(
            {
                "key": key,
                "group_name": (reg.group if reg else d.group if d else "misc")[:40],
                "name": (reg.name if reg else d.name if d else key)[:120],
                "description": (
                    (reg.description or (d.description if d else "")) if reg else (d.description if d else "")
                ),
                "default_enabled": d.default_enabled if d else (reg.default_enabled if reg else True),
                "min_plan_tier": d.min_plan_tier if d else (reg.min_plan_tier if reg else "starter"),
                "depends_on": json.dumps(list(d.depends_on if d else (reg.depends_on if reg else ()))),
                "is_core": key.startswith("core."),
            }
        )
    return rows


def seed_features(conn: Connection) -> int:
    rows = _feature_rows()
    conn.execute(
        text(
            "INSERT INTO platform_features (key, group_name, name, description, default_enabled, min_plan_tier, depends_on, is_core) "
            "VALUES (:key, :group_name, :name, :description, :default_enabled, :min_plan_tier, CAST(:depends_on AS jsonb), :is_core) "
            "ON CONFLICT (key) DO UPDATE SET group_name = EXCLUDED.group_name, name = EXCLUDED.name, "
            "description = EXCLUDED.description, default_enabled = EXCLUDED.default_enabled, "
            "min_plan_tier = EXCLUDED.min_plan_tier, depends_on = EXCLUDED.depends_on, is_core = EXCLUDED.is_core, "
            "updated_at = NOW()"
        ),
        rows,
    )
    return len(rows)


def plan_enabled_features(tier: str) -> list[str]:
    """A tier includes every key at or below it whose default is on (docs/Feature_Flags.md §3)."""
    idx = TIER_ORDER.index(tier)
    return sorted(
        r["key"]
        for r in _feature_rows()
        if r["default_enabled"] and TIER_ORDER.index(r["min_plan_tier"]) <= idx and not r["is_core"]
    )


def seed_plans(conn: Connection) -> tuple[int, int]:
    conn.execute(
        text(
            "INSERT INTO subscription_plans (code, name, tier, student_limit, staff_limit, storage_gb, sms_credits, enabled_features) "
            "VALUES (:code, :name, :tier, :students, :staff, :gb, :sms, '[]') ON CONFLICT DO NOTHING"
        ),
        [
            {"code": c, "name": n, "tier": t, "students": s, "staff": st, "gb": gb, "sms": sms}
            for c, n, t, s, st, gb, sms in PLANS
        ],
    )
    updated = 0
    for tier in TIER_ORDER:
        res = conn.execute(
            text(
                "UPDATE subscription_plans SET enabled_features = CAST(:f AS jsonb), updated_at = NOW() WHERE tier = :tier"
            ),
            {"f": json.dumps(plan_enabled_features(tier)), "tier": tier},
        )
        updated += res.rowcount or 0
    plans = int(conn.execute(text("SELECT count(*) FROM subscription_plans")).scalar_one())
    return plans, updated


def seed_packs(conn: Connection) -> list[str]:
    from app.core.packs import pack_codes

    codes = pack_codes()
    conn.execute(
        text(
            "INSERT INTO platform_settings (key, value) VALUES ('regulatory_packs', CAST(:v AS jsonb)) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()"
        ),
        {"v": json.dumps(codes)},
    )
    return codes


def seed_registries(conn: Connection) -> dict[str, Any]:
    """Everything the data-only revision / seed_platform.py / install seeds (no users)."""
    perms = seed_permissions(conn)
    roles_created, grants = seed_role_templates(conn)
    features = seed_features(conn)
    plans, tiers = seed_plans(conn)
    packs = seed_packs(conn)
    from app.services.institution_defaults import seed_phase03_platform

    phase03 = seed_phase03_platform(conn)  # settings template, theme tokens, number-sequence patterns (Phase 03)
    return {
        "permissions": perms,
        "role_templates_created": roles_created,
        "role_template_grants_added": grants,
        "features": features,
        "plans": plans,
        "plan_tiers_updated": tiers,
        "packs": packs,
        "settings_template_keys": phase03["settings_keys"],
    }


def is_installed(conn: Connection) -> bool:
    row = conn.execute(text("SELECT value FROM platform_settings WHERE key = 'installed'")).first()
    return bool(row and row[0])


# ---- the endpoint service ---------------------------------------------------------------------------------------
class InstallService:
    """``POST /install`` (public, one-time) — Prompts/02 §02.6 ``install_service``."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def install(
        self, *, install_key: str, email: str, password: str, username: str, request: Any = None
    ) -> dict[str, Any]:
        if install_key != settings.INSTALL_SECRET_KEY:
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "Invalid install key")
        conn = await self.db.connection()
        if await conn.run_sync(is_installed):
            raise APIError(409, ErrorCode.CONFLICT, "The platform is already installed")
        check_password_policy(password)
        counts = await conn.run_sync(seed_registries)
        existing = (
            await self.db.execute(text("SELECT id FROM users WHERE is_super_admin AND deleted_at IS NULL LIMIT 1"))
        ).first()
        if existing:
            # A super admin already exists (seed_platform / a previous install): the install key must never be able to
            # reset live platform credentials — the account is kept untouched and only the registries are (re)seeded.
            super_admin_id = uuid.UUID(str(existing[0]))
        else:
            super_admin_id = uuid.uuid4()
            await self.db.execute(
                text(
                    "INSERT INTO users (id, institution_id, username, email, password_hash, display_name, user_type, "
                    "is_super_admin, is_verified, must_change_password) VALUES (:id, NULL, :username, :email, :hash, "
                    "'Platform Super Admin', 'platform', TRUE, TRUE, TRUE)"
                ),
                {"id": super_admin_id, "username": username, "email": email, "hash": hash_password(password)},
            )
        installed_at = datetime.now(UTC)
        await self.db.execute(
            text(
                "INSERT INTO platform_settings (key, value, updated_by) VALUES ('installed', CAST(:v AS jsonb), :u) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_by = EXCLUDED.updated_by, updated_at = NOW()"
            ),
            {"v": json.dumps({"at": installed_at.isoformat(), "version": "0.1.0"}), "u": super_admin_id},
        )
        await log_audit(
            self.db,
            principal=None,
            module="settings",
            action="install",
            record_type="platform",
            record_id=None,
            new={"super_admin_id": str(super_admin_id), **{k: v for k, v in counts.items() if k != "packs"}},
            request=request,
        )
        total_roles = int(
            (await self.db.execute(text("SELECT count(*) FROM roles WHERE institution_id IS NULL"))).scalar_one()
        )
        return {
            "installed_at": installed_at,
            "permissions": counts["permissions"],
            "role_templates": total_roles,
            "features": counts["features"],
            "plans": counts["plans"],
            "super_admin_id": super_admin_id,
        }
