"""phase37 audit logs, security events & settings seed — data only (no tables)

Revision ID: 0037
Revises: 0036
Create Date: 2026-10-27

Prompts/37 §37.2. ``platform_settings['settings_catalogue']`` holds the metadata of every settings key of Phases 03–37
(category, type, default, validation, ``scope: platform|institution|college``, ``locked_by: plan|env|none``,
``requires_restart``, help text, ``depends_on``, ``sensitive`` — built by ``app.core.settings_catalogue``); the
institution defaults add ``privacy.retention`` (retention per data class + ``legal_hold``), ``audit.chain_verify_daily``,
``audit.digest_signing_key_id``, ``audit.anomaly_rules``, ``audit.alert_recipients``, ``audit.sensitive_change_notify``
and the platform-scoped ``security.jwt_kid``; role templates are re-seeded with the Phase 37 grants
(``audit_logs:view`` for every role, ``audit_logs:security`` / ``exams:audit`` / ``settings:view`` …) +
``BACKFILL_GRANTS["0037"]``; notification templates ``audit.chain_broken``, ``audit.anomaly``,
``settings.changed_sensitive``, ``retention.archive_done``, ``retention.legal_hold_set``. Digests, anomalies, legal
holds and manifests live in ``institution_settings`` category ``audit_meta``. Demo data:
``seed_demo_institution.py --only audit``. ``downgrade()`` removes the catalogue row (other data rows stay).
"""

import json
from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

revision: str = "0037"
down_revision: str | None = "0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from app.core.settings_catalogue import catalogue_json
    from app.core.settings_template import template_json
    from app.services.install_service import seed_role_templates
    from app.services.institution_defaults import backfill_role_grants, seed_institution_defaults, seed_phase04_platform

    conn = op.get_bind()
    for key, value in (("settings_catalogue", catalogue_json()), ("settings_template", template_json())):
        conn.execute(
            text(
                "INSERT INTO platform_settings (key, value) VALUES (:k, CAST(:v AS jsonb)) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()"
            ),
            {"k": key, "v": json.dumps(value, default=str)},
        )
    _, grants = seed_role_templates(conn)
    backfilled = backfill_role_grants(conn, "0037")
    platform = seed_phase04_platform(conn)
    settings = 0
    for iid, pack in conn.execute(text("SELECT id, regulatory_pack FROM institutions WHERE deleted_at IS NULL")).all():
        settings += seed_institution_defaults(conn, iid, pack)["settings"]
    print(  # noqa: T201 - alembic log
        f"  settings_catalogue keys={len(catalogue_json())} template_grants+={grants} tenant_grants+={backfilled} "
        f"notification_templates+={platform['notification_templates']} settings+={settings}"
    )


def downgrade() -> None:
    op.get_bind().execute(text("DELETE FROM platform_settings WHERE key = 'settings_catalogue'"))
