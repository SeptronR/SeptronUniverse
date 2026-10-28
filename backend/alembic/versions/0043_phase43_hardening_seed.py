"""phase43 testing, security & privacy hardening seed — data + grants

Revision ID: 0043
Revises: 0042
Create Date: 2026-10-28

Prompts/43 §43.2. Modules ``privacy`` / ``security`` / ``qa`` (+ ``qa:run``) and the ``privacy_officer`` role template
(54 templates), cloned into every tenant; ``BACKFILL_GRANTS["0043"]`` (security officer posture, auditor reads).
``platform_settings``: ``privacy.purposes`` (10 purposes, en/hi), ``privacy.notices`` (7 notices), ``privacy.dsr``,
``privacy.pii_inventory`` (``app/core/pii_inventory.json``), ``security.headers``, ``security.password_policy``,
``security.rate_limits``, ``security.jwt_rotation_days``; notification templates ``privacy.*`` / ``security.*`` /
``qa.suite_finished``. Hardening: the application role loses ``UPDATE`` / ``DELETE`` / ``TRUNCATE`` on ``audit_logs`` and
every partition (the table is append-only; archival runs on the platform role). Demo data:
``seed_demo_institution.py --only hardening``.
"""

import json
from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

revision: str = "0043"
down_revision: str | None = "0042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "universe_app"
SECURITY = {
    "security.headers": {
        "hsts_max_age": 31536000,
        "csp_report_uri": "/api/v1/security/csp-report",
        "frame_ancestors": "'none'",
    },
    "security.password_policy": {"min_length": 10, "classes": 3, "history": 5, "breached_check": True},
    "security.rate_limits": {"public": "60/m", "auth": "10/m", "api_key_default": 600},
    "security.jwt_rotation_days": 90,
}


def upgrade() -> None:
    from app.core.pii_inventory import load_inventory
    from app.core.privacy_registry import DSR_DEFAULTS, notices_json, purposes_json
    from app.services.install_service import seed_features, seed_permissions, seed_role_templates
    from app.services.institution_defaults import backfill_role_grants, seed_phase04_platform

    conn = op.get_bind()
    perms = seed_permissions(conn)
    _, grants = seed_role_templates(conn)
    features = seed_features(conn)
    roles = 0
    tpl = conn.execute(
        text(
            "SELECT id, name, description, default_scope_type, portal FROM roles WHERE institution_id IS NULL AND slug = 'privacy_officer'"
        )
    ).first()
    for (iid,) in conn.execute(text("SELECT id FROM institutions WHERE deleted_at IS NULL")).all():
        if (
            tpl is None
            or conn.execute(
                text("SELECT 1 FROM roles WHERE institution_id = :i AND slug = 'privacy_officer'"), {"i": iid}
            ).first()
        ):
            continue
        rid = conn.execute(
            text(
                "INSERT INTO roles (institution_id, name, slug, description, is_system, default_scope_type, portal) "
                "VALUES (:i, :n, 'privacy_officer', :d, TRUE, :sc, :p) RETURNING id"
            ),
            {"i": iid, "n": tpl.name, "d": tpl.description, "sc": tpl.default_scope_type, "p": tpl.portal},
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO role_permissions (role_id, permission_id) SELECT :r, permission_id FROM role_permissions "
                "WHERE role_id = :t ON CONFLICT DO NOTHING"
            ),
            {"r": rid, "t": tpl.id},
        )
        roles += 1
    backfilled = backfill_role_grants(conn, "0043")
    # the office modules are granted explicitly: drop any privacy / security / qa grant a role's template lacks
    from app.core.rbac.registry import ROLE_TEMPLATES

    pruned = 0
    for slug, grants_ in ROLE_TEMPLATES.items():
        if "*:*" in grants_:
            continue
        keep = sorted(g for g in grants_ if g.split(":", 1)[0] in ("privacy", "security", "qa"))
        res = conn.execute(
            text(
                "DELETE FROM role_permissions rp USING roles r, permissions p WHERE rp.role_id = r.id AND rp.permission_id = p.id "
                "AND r.slug = :s AND p.module IN ('privacy', 'security', 'qa') AND NOT ((p.module || ':' || p.action) = ANY(:k))"
            ),
            {"s": slug, "k": keep},
        )
        pruned += res.rowcount or 0
    values = {
        "privacy.purposes": purposes_json(),
        "privacy.notices": notices_json(),
        "privacy.dsr": DSR_DEFAULTS,
        "privacy.pii_inventory": load_inventory(),
        **SECURITY,
    }
    for k, v in values.items():
        keep = k in ("privacy.notices", "privacy.dsr", *SECURITY)  # operator edits survive re-runs
        conn.execute(
            text(
                "INSERT INTO platform_settings (key, value) VALUES (:k, CAST(:v AS jsonb)) "
                + (
                    "ON CONFLICT (key) DO NOTHING"
                    if keep
                    else "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()"
                )
            ),
            {"k": k, "v": json.dumps(v)},
        )
    platform = seed_phase04_platform(conn)
    conn.execute(
        text(
            f"""
            DO $$
            DECLARE part regclass;
            BEGIN
              IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                REVOKE UPDATE, DELETE, TRUNCATE ON audit_logs FROM {APP_ROLE};
                FOR part IN SELECT inhrelid::regclass FROM pg_inherits WHERE inhparent = 'audit_logs'::regclass LOOP
                  EXECUTE format('REVOKE UPDATE, DELETE, TRUNCATE ON %s FROM {APP_ROLE}', part);
                END LOOP;
              END IF;
            END $$;
            """
        )
    )
    print(  # noqa: T201
        f"  permissions+={perms} template_grants+={grants} features={features} tenant_roles+={roles} "
        f"tenant_grants+={backfilled} pruned={pruned} notification_templates+={platform['notification_templates']}"
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        text("DELETE FROM platform_settings WHERE key = ANY(:k)"),
        {"k": ["privacy.purposes", "privacy.pii_inventory", *SECURITY]},
    )
    conn.execute(text(f"GRANT UPDATE, DELETE ON audit_logs TO {APP_ROLE}"))
