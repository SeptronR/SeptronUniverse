"""phase41 integrations hub, platform APIs & data migration toolkit seed — data only

Revision ID: 0041
Revises: 0040
Create Date: 2026-10-28

Prompts/41 §41.2. ``platform_settings``: ``integrations.providers`` (catalogue snapshot from
``app/integrations/catalogue.py``), ``integrations.platform_defaults`` (empty — the operator fills the SaaS billing /
messaging providers), ``webhooks.events`` (event catalogue), ``imports.templates`` (entity templates from
``import_hooks``). Feature keys ``integrations.*`` / ``data.migration_toolkit``; notification templates
``integrations.*``, ``imports.*``, ``exports.ready``. Settings come from the template (no rows). Demo data:
``seed_demo_institution.py --only integrations``.
"""

import json
from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

revision: str = "0041"
down_revision: str | None = "0040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
KEYS = ("integrations.providers", "integrations.platform_defaults", "webhooks.events", "imports.templates")


def upgrade() -> None:
    from app.integrations.catalogue import catalogue_json
    from app.services.install_service import seed_features
    from app.services.institution_defaults import seed_phase04_platform
    from app.services.integrations.import_hooks import HOOKS
    from app.services.integrations.webhook_service import EVENT_CATALOGUE

    conn = op.get_bind()
    features = seed_features(conn)
    values = {
        "integrations.providers": catalogue_json(),
        "integrations.platform_defaults": {},
        "webhooks.events": [{"event_type": k, "description": v} for k, v in EVENT_CATALOGUE.items()],
        "imports.templates": [{"entity": h.entity, "label": h.label, "module": h.module, "columns": h.columns} for h in HOOKS.values()],
    }
    for k, v in values.items():
        conn.execute(
            text(
                "INSERT INTO platform_settings (key, value) VALUES (:k, CAST(:v AS jsonb)) "
                + ("ON CONFLICT (key) DO NOTHING" if k == "integrations.platform_defaults" else "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()")
            ),
            {"k": k, "v": json.dumps(v)},
        )
    platform = seed_phase04_platform(conn)
    print(f"  features={features} notification_templates+={platform['notification_templates']}")  # noqa: T201


def downgrade() -> None:
    op.get_bind().execute(text("DELETE FROM platform_settings WHERE key = ANY(:k)"), {"k": list(KEYS)})
